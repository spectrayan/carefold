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

"""Automated Pack Import & Single-Source Verification Test.

Enforces that `carefold` is the sole package in `backend/src/` and exposes `get_pack()`
for the `yarvelle.packs` entry-point without booting the FastAPI server shell (`carefold.main`).
"""

from pathlib import Path
import subprocess
import sys


def test_isolated_pack_import():
    """Verifies that carefold and all its health pack subpackages import without booting carefold.main."""
    script = """
import sys

class BlockAppMainFinder:
    def find_spec(self, fullname, path, target=None):
        if fullname == "carefold.main" or fullname.startswith("carefold.main."):
            raise ImportError(
                f"Blocked app-shell import of '{fullname}'. "
                "carefold:get_pack() must operate as a pack without importing carefold.main."
            )
        return None

sys.meta_path.insert(0, BlockAppMainFinder())

# 1. Import pack root
import carefold
assert hasattr(carefold, "get_pack"), "carefold must expose get_pack()"
assert hasattr(carefold, "__version__"), "carefold must expose __version__"

# 2. Discover pack via factory
pack = carefold.get_pack()
assert pack.id == "health"
assert pack.domain == "health"
assert pack.version == carefold.__version__

# 3. Verify health ToolSpecs (17 tools)
from carefold.tools import get_health_tool_specs
specs = get_health_tool_specs()
assert len(specs) == 17, f"Expected 17 health tool specs, got {len(specs)}"
assert len(pack.tools) == 17, f"Expected 17 tools in pack manifest, got {len(pack.tools)}"

# 4. Verify health SafetyPolicy
from carefold.safety import CarefoldHealthSafetyPolicy
policy = CarefoldHealthSafetyPolicy()
assert policy is not None
assert pack.safety_policy is not None
assert len(policy.get_forbidden_intents()) > 0

# 5. Verify health Routers (9 routers)
from carefold.routers import get_health_router_contributions
routers = get_health_router_contributions()
assert len(routers) == 9, f"Expected 9 health router contributions, got {len(routers)}"
assert len(pack.routers) == 9, f"Expected 9 routers in pack manifest, got {len(pack.routers)}"

# 6. Verify Scoped Models (7 models)
from carefold.models import (
    Appointment,
    CompanionDevice,
    HealthResource,
    ImportBatch,
    PreventiveRecord,
    SchoolForm,
    SchoolIcsFeed,
)
assert len(pack.scoped_models) == 7

# 7. Assert sys.modules contains zero carefold.main modules
main_leaks = [m for m in sys.modules if m == "carefold.main" or m.startswith("carefold.main.")]
assert not main_leaks, f"Detected app main leakage in sys.modules: {main_leaks}"

print("ISOLATED_PACK_OK")
"""
    repo_root = Path(__file__).resolve().parents[3]
    pythonpath = f"{repo_root}/backend/src"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": pythonpath,
            "PATH": sys.exec_prefix + "/bin:/usr/bin:/bin",
        },
    )
    assert proc.returncode == 0, f"Subprocess failed with code {proc.returncode}:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    assert "ISOLATED_PACK_OK" in proc.stdout


def test_single_source_directory_in_backend_src():
    """Enforces that backend/src/ contains strictly ONE Python package folder (`carefold`)."""
    repo_root = Path(__file__).resolve().parents[3]
    src_dir = repo_root / "backend" / "src"
    pkg_dirs = [p.name for p in src_dir.iterdir() if p.is_dir() and not p.name.startswith(".") and not p.name.endswith(".egg-info")]
    assert pkg_dirs == ["carefold"], f"Expected only ['carefold'] in backend/src/, found: {pkg_dirs}"

