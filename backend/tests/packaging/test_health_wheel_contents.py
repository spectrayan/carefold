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

"""Packaging test asserting that built carefold-health wheel contains bundled agents, skills, and entry points."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile
import pytest

SPECIALIST_AGENTS = [
    "benefits-coordinator",
    "heart-care-coordinator",
    "claims-appeals-coordinator",
    "skin-care-coordinator",
    "diabetes-thyroid-coordinator",
    "ent-care-coordinator",
    "eye-care-coordinator",
    "prescription-cost-coordinator",
    "digestive-health-coordinator",
    "habit-coordinator",
    "blood-health-coordinator",
    "kidney-care-coordinator",
    "brain-nerve-health-coordinator",
    "cancer-care-coordinator",
    "dental-care-coordinator",
    "bone-joint-care-coordinator",
    "foot-care-coordinator",
    "prior-authorization-coordinator",
    "lung-breathing-coordinator",
    "records-coordinator",
    "autoimmune-care-coordinator",
    "bladder-pelvic-health-coordinator",
    "circulation-vein-care-coordinator",
    "appointment-prep-coordinator",
]

HEALTH_SYSTEM_AGENTS = [
    "quality-reviewer",
    "triage-auditor",
]

HEALTH_SKILLS = [
    "benefits-explainer",
    "cardiology-prep",
    "claims-appeals-prep",
    "clinical-safety-boundaries",
    "derma-prep",
    "emergency-red-flags",
    "endocrinology-prep",
    "ent-prep",
    "formulary-navigation",
    "gastro-prep",
    "habit-checkin",
    "hematology-prep",
    "nephrology-prep",
    "neurology-prep",
    "oncology-prep",
    "oral-health-prep",
    "ortho-prep",
    "podiatry-prep",
    "preventive-care",
    "prior-auth-prep",
    "pulmonology-prep",
    "records-management",
    "rheuma-prep",
    "urology-prep",
    "vascular-prep",
    "vision-prep",
    "visit-prep",
]


def test_health_wheel_contains_all_agents_skills_and_entrypoints(tmp_path: Path):
    """Builds distribution wheel and inspects that all 24 specialist agents, 2 system agents, and 27 skills are bundled."""
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    packaging_dir = repo_root / "backend"
    out_dir = tmp_path / "wheel_dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Build wheel using python -m build --wheel --no-isolation
    cmd = [
        sys.executable,
        "-m",
        "build",
        "--wheel",
        "--no-isolation",
        str(packaging_dir),
        "--outdir",
        str(out_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Failed to build wheel:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    wheel_files = list(out_dir.glob("*.whl"))
    assert len(wheel_files) == 1, f"Expected 1 wheel file in {out_dir}, found: {wheel_files}"
    wheel_path = wheel_files[0]

    with zipfile.ZipFile(wheel_path, "r") as z:
        names = set(z.namelist())

        # 2. Assert all 24 specialist agents are present
        for agent_name in SPECIALIST_AGENTS:
            agent_manifest = f"carefold/_content/agents/{agent_name}/agent.yaml"
            assert agent_manifest in names, f"Built wheel is missing specialist agent: {agent_manifest}"

        # 3. Assert all 2 health system agents are present
        for sys_agent in HEALTH_SYSTEM_AGENTS:
            sys_manifest = f"carefold/_content/agents/_system/{sys_agent}/agent.yaml"
            assert sys_manifest in names, f"Built wheel is missing health system agent: {sys_manifest}"

        # 4. Assert all 27 health skills are present
        for skill_name in HEALTH_SKILLS:
            skill_manifest = f"carefold/_content/skills/{skill_name}/SKILL.md"
            assert skill_manifest in names, f"Built wheel is missing health skill: {skill_manifest}"

        # 5. Assert entry point in .dist-info
        entry_points_files = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
        assert len(entry_points_files) == 1, f"Expected 1 entry_points.txt file, found: {entry_points_files}"
        ep_content = z.read(entry_points_files[0]).decode("utf-8")

        assert "[yarvelle.packs]" in ep_content
        assert "health = carefold:get_pack" in ep_content

