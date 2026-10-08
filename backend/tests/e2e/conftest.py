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

"""Shared fixtures and configuration for Carefold E2E test suite."""

import asyncio
import concurrent.futures
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.main import app
from carefold.schemas.manifest import AgentManifest
from carefold.schemas.tool import ToolResult
from carefold.tools.attach_read import execute_attach_read
from carefold.audit.logger import record_audit


@pytest.fixture(scope="session")
def e2e_repo_root() -> Path:
    """Returns absolute path to Carefold repository root."""
    return Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture
def e2e_workspace(tmp_path: Path, e2e_repo_root: Path):
    """Sets up an isolated, sandboxed test workspace."""
    ws = tmp_path / "e2e_workspace"
    ws.mkdir(parents=True)

    # Scaffolding directories
    agents_dir = ws / "agents"
    skills_dir = ws / "skills"
    attachments_dir = ws / "attachments"
    logs_dir = ws / "logs"
    notes_dir = ws / "workspace" / "notes"

    attachments_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    notes_dir.mkdir(parents=True)

    # Copy bundled agents and skills from repo root if they exist
    repo_agents = e2e_repo_root / "agents"
    repo_skills = e2e_repo_root / "skills"

    if repo_agents.is_dir():
        shutil.copytree(repo_agents, agents_dir)
    else:
        agents_dir.mkdir()

    if repo_skills.is_dir():
        shutil.copytree(repo_skills, skills_dir)
    else:
        skills_dir.mkdir()

    # Create sample attachment files
    sample_text_path = attachments_dir / "sample_visit.txt"
    sample_text_path.write_text(
        "CLINICAL VISIT SUMMARY\n"
        "Patient: Jane Smith, MRN: MRN44921, SSN: 123-45-6789, Phone: (555) 234-5678\n"
        "Address: 123 Elm Street, Metropolis, NY 10001\n"
        "Reason for visit: Annual physical and persistent dry cough.\n"
        "Physician Instructions: Drink plenty of fluids, check temperature twice daily.\n"
        "Follow-up: Return in 4 weeks if cough persists.\n"
        "Questions: Ask if fever exceeds 101 F.\n",
        encoding="utf-8"
    )

    sample_insurance_path = attachments_dir / "sample_insurance.txt"
    sample_insurance_path.write_text(
        "SCHEDULE OF BENEFITS & COVERAGE\n"
        "Annual Deductible: $1,500 individual / $3,000 family\n"
        "Primary Care Visit Copay: $25\n"
        "Specialist Visit Copay: $50\n"
        "Coinsurance: 20% in-network, 40% out-of-network\n"
        "Out-of-Pocket Maximum: $6,000 individual / $12,000 family\n"
        "Prior Authorization Required: Required for advanced imaging (MRI, CT, PET) and physical therapy over 12 sessions.\n",
        encoding="utf-8"
    )

    # Override application settings for test isolation
    old_root = settings.workspace_root
    old_log = settings.audit_log_path
    old_store = settings.audit_store_bodies
    old_auth = settings.auth_provider

    settings.workspace_root = ws
    settings.audit_log_path = logs_dir / "audit.jsonl"
    settings.audit_store_bodies = False
    settings.auth_provider = "disabled"

    yield ws

    # Restore settings
    settings.workspace_root = old_root
    settings.audit_log_path = old_log
    settings.audit_store_bodies = old_store
    settings.auth_provider = old_auth


@pytest.fixture
def e2e_client(e2e_workspace: Path) -> TestClient:
    """Returns FastAPI TestClient operating inside the isolated workspace."""
    return TestClient(app)


@pytest.fixture
def sample_insurance_text() -> str:
    """Authoritative sample raw text for health insurance benefits."""
    return (
        "SCHEDULE OF BENEFITS & COVERAGE\n"
        "Annual Deductible: $1,500 individual / $3,000 family\n"
        "Primary Care Visit Copay: $25\n"
        "Specialist Visit Copay: $50\n"
        "Coinsurance: 20% in-network, 40% out-of-network\n"
        "Out-of-Pocket Maximum: $6,000 individual / $12,000 family\n"
        "Prior Authorization Required: Required for advanced imaging (MRI, CT, PET) and physical therapy over 12 sessions.\n"
    )


@pytest.fixture
def sample_clinical_text() -> str:
    """Authoritative sample raw text for clinical visit summary with PII."""
    return (
        "CLINICAL VISIT SUMMARY\n"
        "Patient: Jane Smith, MRN: MRN44921, SSN: 123-45-6789, Phone: (555) 234-5678\n"
        "Address: 123 Elm Street, Metropolis, NY 10001\n"
        "Reason for visit: Annual physical and persistent dry cough.\n"
        "Physician Instructions: Drink plenty of fluids, check temperature twice daily.\n"
        "Follow-up: Return in 4 weeks if cough persists.\n"
        "Questions: Ask if fever exceeds 101 F.\n"
    )


@pytest.fixture
def sample_generic_text() -> str:
    """Authoritative sample raw text for generic medical administrative records."""
    return (
        "HOSPITAL ADMINISTRATIVE DISCHARGE INSTRUCTIONS\n"
        "Summary: Patient was admitted for observation following mild dehydration.\n"
        "Vitals on discharge: Heart rate 72 bpm, Blood pressure 120/80 mmHg, SpO2 99%.\n"
        "Key Figures: Total length of stay: 24 hours. IV hydration: 2000 mL saline.\n"
        "Sections: Discharge Medication, Dietary Restrictions, Activity Limitations.\n"
    )


def read_attachment_sync(raw_path: str, workspace_root: Path) -> ToolResult:
    """Synchronous helper to run execute_attach_read safely even inside running loops."""
    ctx = type(
        "MockContext",
        (),
        {
            "workspace_root": workspace_root,
            "skills_dir": workspace_root / "skills",
            "agent": AgentManifest(id="test-agent", title="Test Agent", persona="Clinical Steward"),
        },
    )()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(lambda: asyncio.run(execute_attach_read({"path": raw_path}, ctx))).result()
    return asyncio.run(execute_attach_read({"path": raw_path}, ctx))


def record_audit_sync(
    event: Dict[str, Any],
    log_path: Optional[Path] = None,
    store_bodies: bool = False
) -> None:
    """Synchronous helper to run record_audit safely even inside running loops."""
    # Ensure mandatory fields
    if "agent_id" not in event:
        event["agent_id"] = "test-agent"
    if "event" not in event:
        event["event"] = "run"
    elif event["event"] not in ("run", "tool", "refuse", "error"):
        # Map common aliases
        if event["event"] in ("refusal", "refused"):
            event["event"] = "refuse"
        elif event["event"] in ("scenario_complete", "boundary_test", "unicode_test", "empty_event"):
            event["event"] = "run"
        else:
            event["event"] = "run"

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(lambda: asyncio.run(record_audit(event, log_path=log_path, store_bodies=store_bodies))).result()
            return
    asyncio.run(record_audit(event, log_path=log_path, store_bodies=store_bodies))
