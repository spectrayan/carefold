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

"""Neutral Words Scan Test for Core Backend Modules.

Enforces that domain-specific health terms ('clinical', 'patient', 'health', 'medical')
do not leak into generic core modules without explicit allowlisting. Serves as a ratchet
that can only decrease as Steps C1-C3 decouple the architecture.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Dict, List, Tuple
import pytest

# Core directories in backend/src/carefold intended for yarvelle-core
CORE_PATHS = [
    "audit",
    "auth",
    "config.py",
    "constants",
    "db",
    "engine",
    "i18n",
    "loaders",
    "logging.py",
    "memory",
    "middleware",
    "model",
    "schemas",
    "search",
    "settings",
    "storage",
    "templates",
    "vault",
    "workflows",
]

DOMAIN_TERMS = ["clinical", "patient", "health", "medical"]
PATTERN = re.compile(r"\b(" + "|".join(DOMAIN_TERMS) + r")\b", re.IGNORECASE)

# Baseline allowlist of maximum allowed hit lines per core relative file.
# Hand-audited in C0 from 01-CAREFOLD-AUDIT.md and termscan.csv.
BASELINE_ALLOWLIST: Dict[str, int] = {
    "constants/api.py": 4,
    "constants/defaults.py": 2,
    "constants/extraction.py": 2,
    "constants/models.py": 1,
    "db/models.py": 34,
    "db/session.py": 5,
    "engine/graph.py": 3,
    "engine/service.py": 3,
    "engine/runtime.py": 0,
    "engine/refusal_node.py": 0,
    "engine/tool_registry.py": 34,
    "i18n/catalog.py": 2,
    "loaders/agent_loader.py": 1,
    "memory/adapters/spector/store.py": 4,
    "memory/adapters/sqlite/catalog_adapter.py": 1,
    "memory/ports/catalog_port.py": 2,
    "memory/ports/memory_port.py": 2,
    "middleware/clinical_safety.py": 6,
    "middleware/skills.py": 10,
    "model/factory.py": 1,
    "model/providers/anthropic_provider.py": 1,
    "model/providers/base.py": 1,
    "model/providers/custom_provider.py": 1,
    "model/providers/google_provider.py": 1,
    "model/providers/ollama_provider.py": 1,
    "model/providers/openai_provider.py": 1,
    "schemas/activity.py": 5,
    "schemas/health.py": 1,
    "schemas/manifest.py": 3,
    "schemas/memory.py": 2,
    "schemas/notes.py": 2,
    "schemas/plan.py": 1,
    "schemas/profiles.py": 1,
    "search/adapters/spector.py": 2,
    "search/chunker.py": 7,
    "search/reranker.py": 7,
    "workflows/nodes/agent_execution_node.py": 1,
    "workflows/nodes/input_guardrail_node.py": 10,
    "workflows/nodes/output_guardrail_node.py": 3,
    "workflows/nodes/reflection_node.py": 2,
    "workflows/nodes/refusal_node.py": 5,
    "workflows/nodes/response_synthesizer_node.py": 2,
    "workflows/nodes/skill_generator_node.py": 21,
    "workflows/state.py": 4,
    "workflows/subgraphs/extraction/dossiers.py": 8,
    "workflows/subgraphs/extraction/grounding.py": 1,
    "workflows/subgraphs/extraction/sanitizer.py": 5,
    "workflows/subgraphs/extraction/subgraph.py": 1,
    "workflows/subgraphs/extraction/tool.py": 3,
}


def test_core_neutral_words_ratchet():
    """Verify core modules contain no domain words beyond the explicit allowlist."""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "carefold"
    assert src_dir.is_dir(), f"Source dir {src_dir} must exist"

    violations: List[str] = []

    for entry_name in CORE_PATHS:
        target = src_dir / entry_name
        files = [target] if target.is_file() else list(target.rglob("*.py"))

        for py_file in files:
            if "__pycache__" in str(py_file) or "health_migrations" in str(py_file):
                continue

            rel_str = str(py_file.relative_to(src_dir))
            lines = py_file.read_text(encoding="utf-8").splitlines()

            # Skip standard 11-line license header
            body_lines = lines[11:]
            hits: List[Tuple[int, str]] = []

            for line_no, line in enumerate(body_lines, start=12):
                # Ignore import lines referencing carefold package or third-party packages
                trimmed = line.strip()
                if trimmed.startswith(("import ", "from ")):
                    continue
                if PATTERN.search(trimmed):
                    hits.append((line_no, trimmed))

            hit_count = len(hits)
            allowed_max = BASELINE_ALLOWLIST.get(rel_str, 0)

            if hit_count > allowed_max:
                violations.append(
                    f"{rel_str}: found {hit_count} domain term lines, allowed maximum is {allowed_max}.\n"
                    + "\n".join(f"  L{num}: {l}" for num, l in hits[:5])
                )

    assert not violations, (
        f"Domain terms leaked into core modules ({len(violations)} files exceeded allowlist):\n"
        + "\n\n".join(violations)
    )
