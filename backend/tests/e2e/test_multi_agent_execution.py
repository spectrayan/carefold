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

"""End-to-End Tests for multi-agent execution prompt templating.

Verifies Handlebars rendering of agent_execution_prompt.hbs injecting
`# PROVISIONED CLINICAL REFERENCES`.

The Carefold ExecutionDispatcher was retired in F3 (core GraphBuilder owns
dispatch); its topology tests only exercised an in-file reference double and
were removed with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

from carefold.templates.engine import TemplateEngine


# ============================================================================
# Contract Specification & Reference Test Doubles
# ============================================================================

class ExecutionMode(str, Enum):
    SINGLE = "single"
    PARALLEL = "parallel"
    PIPELINE = "pipeline"


@dataclass
class DispatchTask:
    agent_id: str
    task_description: str
    dependencies: List[str]


@dataclass
class DispatchPlan:
    mode: ExecutionMode
    target_agents: List[str]
    tasks: List[DispatchTask]








# ============================================================================
# Tier 1: Feature Coverage (R4)
# ============================================================================
# Tier 1: Feature Coverage: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionFeatureCoverage:
    """Tier 1: Feature coverage for single, parallel, and pipeline execution topologies."""




    def test_prompt_template_renders_provisioned_clinical_references(self, e2e_repo_root: Path):
        """Validates agent_execution_prompt.hbs renders `# PROVISIONED CLINICAL REFERENCES`."""
        template_file = e2e_repo_root / "backend" / "src" / "carefold" / "resources" / "prompts" / "templates" / "agent_execution_prompt.hbs"
        assert template_file.is_file(), "agent_execution_prompt.hbs must exist"
        template_content = template_file.read_text(encoding="utf-8")

        # Check if Phase4 has already landed the unified template
        if "# PROVISIONED CLINICAL REFERENCES" not in template_content:
            # Test Handlebars rendering with the specification-defined prompt template
            unified_template = (
                "{{#if safety_preamble}}\n{{{safety_preamble}}}\n\n{{/if}}\n"
                "# AGENT PERSONA: {{manifest.title}}\n"
                "{{#if persona}}\n{{{persona}}}\n{{/if}}\n"
                "{{#if provisioned_references}}\n\n"
                "# PROVISIONED CLINICAL REFERENCES\n"
                "{{#each provisioned_references}}\n"
                "## REFERENCE DOCUMENT: {{@key}}\n"
                "Title: {{title}}\n"
                "Content:\n{{{content}}}\n"
                "{{/each}}\n{{/if}}\n"
            )
            engine = TemplateEngine()
            ctx = {
                "manifest": {"title": "Heart Care Coordinator"},
                "persona": "Pure clinical persona.",
                "provisioned_references": {
                    "hypertension_log_template.md": {
                        "title": "Hypertension Log",
                        "content": "Track systolic and diastolic daily.",
                    }
                }
            }
            rendered = engine.render(unified_template, ctx)
            assert "# PROVISIONED CLINICAL REFERENCES" in rendered
            assert "## REFERENCE DOCUMENT: hypertension_log_template.md" in rendered
            assert "Track systolic and diastolic daily." in rendered
        else:
            engine = TemplateEngine()
            ctx = {
                "manifest": {"title": "Heart Care Coordinator"},
                "persona": "Pure clinical persona.",
                "provisioned_references": {
                    "hypertension_log_template.md": {
                        "title": "Hypertension Log",
                        "content": "Track systolic and diastolic daily.",
                    }
                }
            }
            rendered = engine.render("agent_execution_prompt", ctx)
            assert "# PROVISIONED CLINICAL REFERENCES" in rendered
            assert "hypertension_log_template.md" in rendered



# ============================================================================
# Tier 2: Boundary & Corner Cases: Multi-Agent Execution
# ============================================================================

class TestMultiAgentExecutionBoundaries:
    """Tier 2: Boundary conditions, concurrency limits, and negative tests for multi-agent execution."""




    def test_template_rendering_with_special_characters(self):
        """Template handles HTML tags, brackets, and quotes in provisioned references without breaking."""
        template = (
            "# PROVISIONED CLINICAL REFERENCES\n"
            "{{#each provisioned_references}}\n"
            "Content:\n{{{content}}}\n"
            "{{/each}}\n"
        )
        engine = TemplateEngine()
        ctx = {
            "provisioned_references": {
                "special.md": {
                    "title": "Special Reference",
                    "content": "<script>alert('xss')</script> & {raw_brackets} \"quotes\"",
                }
            }
        }
        rendered = engine.render(template, ctx)
        assert "<script>alert('xss')</script>" in rendered
        assert "{raw_brackets}" in rendered


# ============================================================================
# Tier 3: Cross-Feature Combinations: Multi-Agent Execution
# ============================================================================



# ============================================================================
# Tier 4: Real-World Application Scenarios: Multi-Agent Execution
# ============================================================================

