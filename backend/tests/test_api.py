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

"""Integration tests for Carefold FastAPI REST and SSE endpoints."""

from pathlib import Path
import json
import pytest
from fastapi.testclient import TestClient

from carefold.safety.template import SAFE_REFUSAL_TEMPLATE


# ============================================================================
# Helpers
# ============================================================================

def parse_sse_events(raw_text: str):
    """Parses raw HTTP SSE stream content into structured (event_type, data) dicts."""
    events = []
    current_event = None
    current_data = []

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            if current_event or current_data:
                data_str = "\n".join(current_data)
                try:
                    payload = json.loads(data_str) if data_str else {}
                except Exception:
                    payload = {"raw": data_str}
                events.append({"event": current_event or "message", "data": payload})
                current_event = None
                current_data = []
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current_data.append(line[len("data:"):].strip())

    if current_event or current_data:
        data_str = "\n".join(current_data)
        try:
            payload = json.loads(data_str) if data_str else {}
        except Exception:
            payload = {"raw": data_str}
        events.append({"event": current_event or "message", "data": payload})

    return events


# ============================================================================
# Catalog & Health Tests (Preserved)
# ============================================================================

def test_api_health(client: TestClient):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["version"] == "0.1.0"
    assert "uptime" in data
    assert "workspace" in data
    assert data["workspace"]["agentsCount"] >= 1
    assert data["workspace"]["skillsCount"] >= 1
    assert "ollama" in data
    assert data.get("backendReachable") is True


def test_api_health_excludes_underscore_and_dot_directories(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify GET /api/health excludes dot- and underscore-prefixed directories
    (such as _system, _template, _custom, .hidden) from workspace counts."""
    # Verify against bundled repository workspace
    res = client.get("/api/health")
    assert res.status_code == 200
    workspace = res.json()["workspace"]
    assert workspace["agentsCount"] >= 1
    assert workspace["skillsCount"] >= 1

    # Verify isolated behavior when underscore and dot directories are present
    fake_agents = tmp_path / "agents"
    fake_skills = tmp_path / "skills"
    fake_agents.mkdir()
    fake_skills.mkdir()

    (fake_agents / "agent-one").mkdir()
    (fake_agents / "agent-two").mkdir()
    (fake_agents / "_system").mkdir()
    (fake_agents / "_template").mkdir()
    (fake_agents / "_custom").mkdir()
    (fake_agents / ".hidden").mkdir()

    (fake_skills / "skill-one").mkdir()
    (fake_skills / "_template").mkdir()
    (fake_skills / "_custom").mkdir()
    (fake_skills / ".archive").mkdir()

    from carefold.config import settings
    monkeypatch.setattr(settings, "workspace_root", tmp_path)

    res_temp = client.get("/api/health")
    assert res_temp.status_code == 200
    temp_workspace = res_temp.json()["workspace"]
    assert temp_workspace["agentsCount"] == 2
    assert temp_workspace["skillsCount"] == 1


def test_api_agents_list(client: TestClient):
    res = client.get("/api/agents")
    assert res.status_code == 200
    agents = res.json()
    assert isinstance(agents, list)
    agent_ids = [a["id"] for a in agents]
    assert "visit-steward" in agent_ids
    assert "benefits-guide" in agent_ids
    assert "habit-companion" in agent_ids
    # System agents must be excluded by default
    assert "orchestrator" not in agent_ids
    assert "document-extractor" not in agent_ids
    assert "skill-generator" not in agent_ids
    assert "suggestion-generator" not in agent_ids
    assert "_template" not in agent_ids


def test_api_agents_list_exposes_forbidden_and_consent_flag(client: TestClient):
    """Summaries expose the forbidden-intent list (rendered by the web consent dialog
    before consent is given) and only report clinical_enabled when consent is passed."""
    res = client.get("/api/agents")
    assert res.status_code == 200
    by_id = {a["id"]: a for a in res.json()}

    steward = by_id["visit-steward"]
    assert steward["risk_class"] == "clinical_assist"
    assert "diagnose" in steward["forbidden"]
    assert "replace_emergency_care" in steward["forbidden"]
    assert steward["clinical_enabled"] is False

    consented = {a["id"]: a for a in client.get("/api/agents?allow_clinical=true").json()}
    assert consented["visit-steward"]["clinical_enabled"] is True

    # Non-clinical agents are never gated
    assert by_id["habit-companion"]["clinical_enabled"] is True


def test_api_agents_list_include_hidden(client: TestClient):
    """Verify include_hidden=true returns system agents from _system/ but excludes _template."""
    res = client.get("/api/agents?include_hidden=true")
    assert res.status_code == 200
    agents = res.json()
    agent_ids = [a["id"] for a in agents]

    # User-facing agents
    assert "visit-steward" in agent_ids
    assert "benefits-guide" in agent_ids
    assert "habit-companion" in agent_ids

    # System agents
    assert "orchestrator" in agent_ids
    assert "document-extractor" in agent_ids
    assert "skill-generator" in agent_ids
    assert "suggestion-generator" in agent_ids

    # Template must never be included
    assert "_template" not in agent_ids


def test_api_agents_detail_system_agent(client: TestClient):
    """Verify system agent details can be retrieved by ID and hidden=True."""
    res = client.get("/api/agents/orchestrator")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "orchestrator"
    assert data["hidden"] is True
    assert data["can_delegate"] is True


def test_api_agents_detail_reject_underscore_or_dot(client: TestClient):
    """Verify paths starting with . or _ are rejected with 404."""
    res_template = client.get("/api/agents/_template")
    assert res_template.status_code == 404

    res_system = client.get("/api/agents/_system")
    assert res_system.status_code == 404



def test_api_agents_filter_risk_class(client: TestClient):
    res = client.get("/api/agents?risk_class=admin")
    assert res.status_code == 200
    agents = res.json()
    assert len(agents) >= 1
    assert all(a["risk_class"] == "admin" for a in agents)
    assert any(a["id"] == "benefits-guide" for a in agents)


def test_api_agents_categories(client: TestClient):
    """Verify GET /api/agents/categories returns 200 and tree dictionary."""
    res = client.get("/api/agents/categories")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, dict)
    domains = data.get("domains", data)
    assert "navigation" in domains
    assert "wellness" in domains
    assert domains["navigation"]["count"] >= 1
    assert domains["wellness"]["count"] >= 1
    assert "categories" in domains["navigation"]


def test_api_agents_filter_domain(client: TestClient):
    """Verify GET /api/agents?domain=navigation returns only navigation agents."""
    res = client.get("/api/agents?domain=navigation")
    assert res.status_code == 200
    agents = res.json()
    assert len(agents) >= 1
    assert all(a.get("domain", "").lower() == "navigation" for a in agents)
    agent_ids = [a["id"] for a in agents]
    assert "visit-steward" in agent_ids or "benefits-guide" in agent_ids
    assert "habit-companion" not in agent_ids


def test_api_agents_pagination(client: TestClient):
    """Verify GET /api/agents?page=1&per_page=2 returns exactly 2 agents."""
    res = client.get("/api/agents?page=1&per_page=2")
    assert res.status_code == 200
    agents = res.json()
    assert isinstance(agents, list)
    assert len(agents) == 2

    res_page_2 = client.get("/api/agents?page=2&per_page=2")
    assert res_page_2.status_code == 200
    agents_p2 = res_page_2.json()
    assert isinstance(agents_p2, list)
    p1_ids = {a["id"] for a in agents}
    p2_ids = {a["id"] for a in agents_p2}
    assert p1_ids.isdisjoint(p2_ids)


def test_api_skills_filter_domain_and_pagination(client: TestClient):
    """Verify skills filtering and pagination."""
    res = client.get("/api/skills?domain=wellness")
    assert res.status_code == 200
    skills = res.json()
    assert len(skills) >= 1
    assert all(s.get("domain", "").lower() == "wellness" for s in skills)

    res_paginated = client.get("/api/skills?page=1&per_page=1")
    assert res_paginated.status_code == 200
    paginated_skills = res_paginated.json()
    assert len(paginated_skills) == 1


def test_api_agents_detail(client: TestClient):
    res = client.get("/api/agents/visit-steward?allow_clinical=true")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "visit-steward"
    assert data["title"] == "Visit Steward"
    assert "effectiveTools" in data
    assert set(data["effectiveTools"]) == {"attach-read", "workspace-note", "skill-docs"}
    assert len(data["resolvedSkills"]) == 1
    assert data["resolvedSkills"][0]["id"] == "visit-prep"
    assert len(data["toolDefinitions"]) >= 3


def test_api_agents_detail_not_found(client: TestClient):
    res = client.get("/api/agents/non-existent-agent")
    assert res.status_code == 404


def test_api_skills_list(client: TestClient):
    res = client.get("/api/skills")
    assert res.status_code == 200
    skills = res.json()
    skill_ids = [s["id"] for s in skills]
    assert "visit-prep" in skill_ids
    assert "benefits-explainer" in skill_ids
    assert "habit-checkin" in skill_ids
    assert "_template" not in skill_ids
    assert not any(sid.startswith("_") for sid in skill_ids)


def test_api_skills_detail(client: TestClient):
    res = client.get("/api/skills/visit-prep")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "visit-prep"
    assert "checklist.md" in data["references"]
    assert "questions_guide.md" in data["references"]
    assert data["is_verified"] is True


def test_api_skills_detail_template_direct_lookup(client: TestClient):
    """Verify _template can still be fetched by exact ID for scaffolding."""
    res = client.get("/api/skills/_template")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "_template"


def test_api_skills_detail_not_found(client: TestClient):
    res = client.get("/api/skills/unknown-skill")
    assert res.status_code == 404


def test_api_audit_list(client: TestClient):
    res = client.get("/api/audit")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "limit" in data
    assert "events" in data
    assert isinstance(data["events"], list)


def test_api_chat_validation_errors(client: TestClient):
    # Empty prompt
    res1 = client.post("/api/chat", json={"agentId": "visit-steward", "prompt": ""})
    assert res1.status_code == 400

    # Missing agent
    res2 = client.post("/api/chat", json={"prompt": "Hello"})
    assert res2.status_code == 400

    # Non-existent agent
    res3 = client.post("/api/chat", json={"agentId": "imaginary-agent", "prompt": "Hello"})
    assert res3.status_code == 404


# ============================================================================
# Enhanced SSE Streaming & Session Tests (M7 Requirements)
# ============================================================================

def test_api_chat_stream_mock_success(client: TestClient):
    """Verifies baseline SSE streaming with token chunks, audit event ID, and suggestions."""
    payload = {
        "agentId": "visit-steward",
        "prompt": "Hello! Can you help me prepare for a doctor visit?",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        response.read()
        content = response.text
        assert "event: token" in content
        assert "event: done" in content
        assert "auditEventId" in content

        events = parse_sse_events(content)
        done_ev = next(e for e in events if e["event"] == "done")
        done_data = done_ev["data"]
        assert done_data.get("refused") is False
        suggestions = done_data.get("followUpSuggestions") or done_data.get("suggestions", [])
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 2


def test_api_chat_stream_safety_refusal(client: TestClient):
    """Verifies pre-generation clinical refusal emits refusal and done events over SSE."""
    payload = {
        "agentId": "visit-steward",
        "prompt": "Please diagnose if my rash is shingles.",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        content = response.text
        assert "event: refusal" in content
        assert "forbidden_intent:diagnose" in content
        assert SAFE_REFUSAL_TEMPLATE in content

        events = parse_sse_events(content)
        refusal_ev = next(e for e in events if e["event"] == "refusal")
        assert refusal_ev["data"]["reason"] == "forbidden_intent:diagnose"
        assert refusal_ev["data"]["message"] == SAFE_REFUSAL_TEMPLATE

        done_ev = next(e for e in events if e["event"] == "done")
        assert done_ev["data"]["refused"] is True


def test_api_chat_stream_multi_turn_with_thread_id(client: TestClient):
    """Verifies conversation history continuity across consecutive POST /api/chat calls."""
    thread_id = "test-api-thread-continuity-1"

    # Turn 1
    t1_payload = {
        "agentId": "visit-steward",
        "prompt": "I am scheduling an eye exam for next Friday.",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=t1_payload) as r1:
        assert r1.status_code == 200
        r1.read()
        events1 = parse_sse_events(r1.text)
        done1 = next(e for e in events1 if e["event"] == "done")
        assert done1["data"]["refused"] is False

    # Turn 2 with same threadId
    t2_payload = {
        "agentId": "visit-steward",
        "prompt": "Can you draft questions for that exam?",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=t2_payload) as r2:
        assert r2.status_code == 200
        r2.read()
        events2 = parse_sse_events(r2.text)
        done2 = next(e for e in events2 if e["event"] == "done")
        assert done2["data"]["refused"] is False
        assert len(done2["data"]["fullText"]) > 0


def test_api_chat_stream_with_model_provider_selection(client: TestClient):
    """Verifies that provider and model fields are accepted in request payload."""
    payload = {
        "agentId": "visit-steward",
        "prompt": "Hello there!",
        "provider": "mock",
        "model": "carefold-mock",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        events = parse_sse_events(response.text)
        assert any(e["event"] == "token" for e in events)
        assert any(e["event"] == "done" for e in events)


def test_api_chat_stream_server_restart_simulation(temp_workspace: Path):
    """Simulates an API client connecting across server restart with persisted threadId."""
    thread_id = "api-restart-thread-42"
    from carefold.main import app

    # Instance 1
    client1 = TestClient(app)
    t1_payload = {
        "agentId": "visit-steward",
        "prompt": "My preferred pharmacy is Walgreens on 5th Ave.",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client1.stream("POST", "/api/chat", json=t1_payload) as r1:
        assert r1.status_code == 200
        r1.read()

    # Verify SQLite checkpoints DB created
    assert (temp_workspace / "chats" / "checkpoints.db").is_file()

    # Instance 2 (restart: fresh client instance)
    client2 = TestClient(app)
    t2_payload = {
        "agentId": "visit-steward",
        "prompt": "What pharmacy did I choose?",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client2.stream("POST", "/api/chat", json=t2_payload) as r2:
        assert r2.status_code == 200
        r2.read()
        events2 = parse_sse_events(r2.text)
        done2 = next(e for e in events2 if e["event"] == "done")
        assert done2["data"]["refused"] is False


def test_api_chat_stream_tool_execution_events(client: TestClient, temp_workspace: Path):
    """Verifies tool_start and tool_end events appear in SSE stream."""
    attachments_dir = temp_workspace / "attachments"
    (attachments_dir / "blood_work.txt").write_text("WBC: 6.5, RBC: 4.8", encoding="utf-8")

    payload = {
        "agentId": "visit-steward",
        "prompt": "Review my attached blood_work.txt report please.",
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200
        response.read()
        events = parse_sse_events(response.text)
        event_names = [e["event"] for e in events]
        assert "tool_start" in event_names
        assert "tool_end" in event_names
        assert "done" in event_names

        tool_end_ev = next(e for e in events if e["event"] == "tool_end")
        assert tool_end_ev["data"]["tool"] == "attach-read"
        assert tool_end_ev["data"]["allowed"] is True


def test_api_chat_get_thread_history(client: TestClient, temp_workspace: Path):
    """Verifies GET /api/chat/threads/{thread_id} retrieves persisted thread history."""
    thread_id = "test-history-thread-endpoint"

    # Seed conversation via SSE
    payload = {
        "agentId": "visit-steward",
        "prompt": "Hello from session thread test.",
        "threadId": thread_id,
        "mock": True,
        "allow_clinical": True,
    }
    with client.stream("POST", "/api/chat", json=payload) as r:
        assert r.status_code == 200
        r.read()

    # Query history endpoint
    res = client.get(f"/api/chat/threads/{thread_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["threadId"] == thread_id
    assert "messages" in data
    assert len(data["messages"]) >= 2
    assert any(m["role"] == "user" for m in data["messages"])
    assert any(m["role"] == "assistant" for m in data["messages"])


def test_api_agents_list_taxonomy_fields(client: TestClient):
    """Verify that GET /api/agents includes all 7 taxonomy fields on AgentSummary objects."""
    res = client.get("/api/agents")
    assert res.status_code == 200
    agents = res.json()
    assert isinstance(agents, list)
    by_id = {a["id"]: a for a in agents}

    # Verify visit-steward
    assert "visit-steward" in by_id
    vs = by_id["visit-steward"]
    assert vs["domain"] == "navigation"
    assert vs["category"] == "navigation.appointments"
    assert vs["care_stages"] == ["pre_visit", "during_visit"]
    assert vs["tags"] == ["visit-prep", "appointment", "checklist", "doctor"]
    assert vs["icon"] == "Stethoscope"
    assert vs["maturity"] == "stable"
    assert isinstance(vs["target_audience"], list)

    # Verify benefits-guide
    assert "benefits-guide" in by_id
    bg = by_id["benefits-guide"]
    assert bg["domain"] == "navigation"
    assert bg["category"] == "navigation.insurance"
    assert bg["care_stages"] == ["post_visit", "daily_living"]
    assert bg["tags"] == ["insurance", "benefits", "EOB", "deductible", "copay"]
    assert bg["icon"] == "FileText"
    assert bg["maturity"] == "stable"

    # Verify habit-companion
    assert "habit-companion" in by_id
    hc = by_id["habit-companion"]
    assert hc["domain"] == "wellness"
    assert hc["category"] == "wellness.habits"
    assert hc["care_stages"] == ["daily_living"]
    assert hc["tags"] == ["habits", "hydration", "sleep", "checklist"]
    assert hc["icon"] == "HeartPulse"
    assert hc["maturity"] == "stable"


def test_api_agents_detail_taxonomy_fields(client: TestClient):
    """Verify that GET /api/agents/{agent_id} returns all 7 taxonomy fields on AgentDetailResponse."""
    # 1. visit-steward
    res_vs = client.get("/api/agents/visit-steward?allow_clinical=true")
    assert res_vs.status_code == 200
    data_vs = res_vs.json()
    assert data_vs["domain"] == "navigation"
    assert data_vs["category"] == "navigation.appointments"
    assert data_vs["care_stages"] == ["pre_visit", "during_visit"]
    assert data_vs["tags"] == ["visit-prep", "appointment", "checklist", "doctor"]
    assert data_vs["icon"] == "Stethoscope"
    assert data_vs["maturity"] == "stable"
    assert isinstance(data_vs["target_audience"], list)

    # 2. benefits-guide
    res_bg = client.get("/api/agents/benefits-guide")
    assert res_bg.status_code == 200
    data_bg = res_bg.json()
    assert data_bg["domain"] == "navigation"
    assert data_bg["category"] == "navigation.insurance"
    assert data_bg["care_stages"] == ["post_visit", "daily_living"]
    assert data_bg["tags"] == ["insurance", "benefits", "EOB", "deductible", "copay"]
    assert data_bg["icon"] == "FileText"
    assert data_bg["maturity"] == "stable"

    # 3. habit-companion
    res_hc = client.get("/api/agents/habit-companion")
    assert res_hc.status_code == 200
    data_hc = res_hc.json()
    assert data_hc["domain"] == "wellness"
    assert data_hc["category"] == "wellness.habits"
    assert data_hc["care_stages"] == ["daily_living"]
    assert data_hc["tags"] == ["habits", "hydration", "sleep", "checklist"]
    assert data_hc["icon"] == "HeartPulse"
    assert data_hc["maturity"] == "stable"


def test_api_skills_list_taxonomy_fields(client: TestClient):
    """Verify that GET /api/skills includes domain, category, tags, and human-readable title on SkillSummary."""
    res = client.get("/api/skills")
    assert res.status_code == 200
    skills = res.json()
    assert isinstance(skills, list)
    assert len(skills) >= 3

    valid_domains = {"wellness", "clinical", "therapy", "navigation", "education"}
    for skill in skills:
        assert "domain" in skill
        assert skill["domain"] in valid_domains
        assert "category" in skill
        assert isinstance(skill["category"], str)
        assert "tags" in skill
        assert isinstance(skill["tags"], list)
        assert "title" in skill
        assert isinstance(skill["title"], str)
        assert len(skill["title"]) > 0


def test_api_skills_detail_taxonomy_fields(client: TestClient):
    """Verify that GET /api/skills/{skill_id} returns domain, category, tags, and title on SkillDetailResponse."""
    res = client.get("/api/skills/visit-prep")
    assert res.status_code == 200
    data = res.json()
    assert "domain" in data
    assert data["domain"] in {"wellness", "clinical", "therapy", "navigation", "education"}
    assert "category" in data
    assert isinstance(data["category"], str)
    assert "tags" in data
    assert isinstance(data["tags"], list)
    assert "title" in data
    assert data["title"] == "Clinical Visit Preparation & Agenda Planning"


def test_api_agents_detail_resolved_skills_titles(client: TestClient):
    """Verify that GET /api/agents/{id} returns resolvedSkills with human-readable titles."""
    res = client.get("/api/agents/cardiology-guide?allow_clinical=true")
    assert res.status_code == 200
    data = res.json()
    assert "resolvedSkills" in data
    assert len(data["resolvedSkills"]) > 0
    skill_map = {s["id"]: s for s in data["resolvedSkills"]}
    assert "cardiology-prep" in skill_map
    assert skill_map["cardiology-prep"]["title"] == "Cardiovascular Consultation & Vitals Prep"


def test_api_models_endpoint(client: TestClient):
    """Verify that GET /api/models returns provider models and reachability info."""
    # Test Ollama fallback when daemon is offline
    res = client.get("/api/models?provider=ollama")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "ollama"
    assert "models" in data
    assert "reachable" in data

    # Test cloud provider (e.g. google) returns predefined models
    res_cloud = client.get("/api/models?provider=google")
    assert res_cloud.status_code == 200
    cloud_data = res_cloud.json()
    assert cloud_data["provider"] == "google"
    assert cloud_data["reachable"] is True
    assert len(cloud_data["models"]) > 0

