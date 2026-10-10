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

"""Agent & Skill Taxonomy Schema and Validation Test Suite.

Tests and stress-tests:
1. Schema & Enum Validation (AgentDomain & AgentMaturity):
   - Valid enums, edge case strings, and invalid enum values.
   - Pydantic ValidationError enforcement across all 7 manifest and API models.
2. Backward Compatibility & Defaults Resolution:
   - Manifests completely omitting taxonomy fields.
   - Manifests with partial taxonomy specifications.
   - Default list independence (no mutable shared default state).
3. Adversarial / Boundary Input Handling:
   - Extra / unexpected fields in manifests and payloads.
   - Explicit null values in non-nullable schema fields.
   - Unicode, emoji, and large strings in category and tags.
4. JSON Serialization & Round-Trip Fidelity:
   - model_dump() and model_dump(mode='json').
   - model_dump_json() and model_validate_json() round-trip identity.
5. Loader Integration Stress Tests:
   - End-to-end file-system loading via load_agent() and load_skill().
   - Frontmatter and carefold.yaml precedence, merging, and validation errors.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
import pytest
from pydantic import ValidationError

from carefold.loaders.agent_loader import load_agent, load_all_agents
from carefold.loaders.skill_loader import ManifestValidationError, load_skill
from carefold.schemas.manifest import (
    AgentDetailResponse,
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    AgentSummary,
    CarefoldYaml,
    RiskClass,
    SkillDetailResponse,
    SkillFrontmatter,
    SkillManifest,
    SkillSummary,
)


# ============================================================================
# 1. Schema & Enum Validation (AgentDomain & AgentMaturity)
# ============================================================================

class TestEnumValidation:
    """Stress tests enum enforcement and validation error handling."""

    @pytest.mark.parametrize(
        "domain_val",
        ["wellness", "clinical", "therapy", "navigation", "education"],
    )
    def test_agent_domain_valid_values(self, domain_val: str):
        """All specified domain values must construct successfully."""
        domain_enum = AgentDomain(domain_val)
        assert domain_enum.value == domain_val

        # Test within AgentManifest
        agent = AgentManifest(
            id="test-agent",
            title="Test Agent",
            persona="Helper",
            domain=domain_enum,
        )
        assert agent.domain == domain_enum
        assert agent.domain == domain_val

        # Also accepts raw string matching enum value
        agent_str = AgentManifest(
            id="test-agent-str",
            title="Test Agent Str",
            persona="Helper",
            domain=domain_val,  # type: ignore[arg-type]
        )
        assert agent_str.domain == domain_enum

    @pytest.mark.parametrize(
        "invalid_domain",
        [
            "invalid_domain",
            "admin",
            "diagnostics",
            "WELLNESS",
            "Clinical",
            "wellness ",
            "",
            "   ",
            123,
            True,
            False,
        ],
    )
    def test_agent_domain_invalid_values_raise_validation_error(self, invalid_domain: Any):
        """Invalid domain values must raise pydantic.ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AgentManifest(
                id="test-agent",
                title="Test Agent",
                persona="Helper",
                domain=invalid_domain,
            )
        assert "domain" in str(exc_info.value)

    @pytest.mark.parametrize(
        "maturity_val",
        ["draft", "beta", "stable", "deprecated"],
    )
    def test_agent_maturity_valid_values(self, maturity_val: str):
        """All specified maturity values must construct successfully."""
        maturity_enum = AgentMaturity(maturity_val)
        assert maturity_enum.value == maturity_val

        agent = AgentManifest(
            id="test-agent",
            title="Test Agent",
            persona="Helper",
            maturity=maturity_enum,
        )
        assert agent.maturity == maturity_enum
        assert agent.maturity == maturity_val

        # Also accepts raw string
        agent_str = AgentManifest(
            id="test-agent-str",
            title="Test Agent Str",
            persona="Helper",
            maturity=maturity_val,  # type: ignore[arg-type]
        )
        assert agent_str.maturity == maturity_enum

    @pytest.mark.parametrize(
        "invalid_maturity",
        [
            "production",
            "alpha",
            "immortal",
            "STABLE",
            "Stable",
            "stable ",
            "",
            "   ",
            0,
            1,
            True,
        ],
    )
    def test_agent_maturity_invalid_values_raise_validation_error(self, invalid_maturity: Any):
        """Invalid maturity values must raise pydantic.ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AgentManifest(
                id="test-agent",
                title="Test Agent",
                persona="Helper",
                maturity=invalid_maturity,
            )
        assert "maturity" in str(exc_info.value)

    def test_enum_validation_across_all_schema_types(self):
        """Check that invalid domain/maturity raises across all manifest and response models."""
        # 1. SkillManifest invalid domain
        with pytest.raises(ValidationError) as exc:
            SkillManifest(
                id="s1",
                name="s1",
                description="desc",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)

        # 2. AgentSummary invalid domain
        with pytest.raises(ValidationError) as exc:
            AgentSummary(
                id="a1",
                title="a1",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)

        # 3. AgentSummary invalid maturity
        with pytest.raises(ValidationError) as exc:
            AgentSummary(
                id="a1",
                title="a1",
                maturity="unreleased",  # type: ignore[arg-type]
            )
        assert "maturity" in str(exc.value)

        # 4. AgentDetailResponse invalid domain
        with pytest.raises(ValidationError) as exc:
            AgentDetailResponse(
                id="a1",
                title="a1",
                persona="role",
                personaSummary="summary",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)

        # 5. AgentDetailResponse invalid maturity
        with pytest.raises(ValidationError) as exc:
            AgentDetailResponse(
                id="a1",
                title="a1",
                persona="role",
                personaSummary="summary",
                maturity="unreleased",  # type: ignore[arg-type]
            )
        assert "maturity" in str(exc.value)

        # 6. SkillSummary invalid domain
        with pytest.raises(ValidationError) as exc:
            SkillSummary(
                id="s1",
                name="s1",
                description="desc",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)

        # 7. SkillDetailResponse invalid domain
        with pytest.raises(ValidationError) as exc:
            SkillDetailResponse(
                id="s1",
                name="s1",
                description="desc",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)

        # 8. CarefoldYaml invalid domain
        with pytest.raises(ValidationError) as exc:
            CarefoldYaml(domain="invalid_dom")  # type: ignore[arg-type]
        assert "domain" in str(exc.value)

        # 9. SkillFrontmatter invalid domain
        with pytest.raises(ValidationError) as exc:
            SkillFrontmatter(
                name="s1",
                description="desc",
                domain="invalid_dom",  # type: ignore[arg-type]
            )
        assert "domain" in str(exc.value)


# ============================================================================
# 2. Backward Compatibility & Defaults Resolution
# ============================================================================

class TestDefaultsAndBackwardCompatibility:
    """Verifies that manifests omitting taxonomy fields receive sensible defaults."""

    def test_agent_manifest_complete_defaults(self):
        """Omitting all 7 taxonomy fields on AgentManifest populates expected defaults."""
        agent = AgentManifest(
            id="minimal-agent",
            title="Minimal Agent",
            persona="Friendly assistant",
        )
        assert agent.domain == AgentDomain.WELLNESS
        assert agent.domain == "wellness"
        assert agent.category == ""
        assert agent.care_stages == []
        assert agent.target_audience == []
        assert agent.tags == []
        assert agent.icon == "Shield"
        assert agent.maturity == AgentMaturity.STABLE
        assert agent.maturity == "stable"

    def test_skill_manifest_complete_defaults(self):
        """Omitting all 3 taxonomy fields on SkillManifest populates expected defaults."""
        skill = SkillManifest(
            id="minimal-skill",
            name="minimal-skill",
            description="Minimal skill description",
        )
        assert skill.domain == AgentDomain.WELLNESS
        assert skill.domain == "wellness"
        assert skill.category == ""
        assert skill.tags == []

    def test_agent_summary_and_detail_defaults(self):
        """Response schemas default taxonomy fields appropriately."""
        summary = AgentSummary(
            id="sum-agent",
            title="Summary Agent",
        )
        assert summary.domain == AgentDomain.WELLNESS
        assert summary.category == ""
        assert summary.care_stages == []
        assert summary.target_audience == []
        assert summary.tags == []
        assert summary.icon == "Shield"
        assert summary.maturity == AgentMaturity.STABLE

        detail = AgentDetailResponse(
            id="det-agent",
            title="Detail Agent",
            persona="Bot",
            personaSummary="Bot summary",
        )
        assert detail.domain == AgentDomain.WELLNESS
        assert detail.category == ""
        assert detail.care_stages == []
        assert detail.target_audience == []
        assert detail.tags == []
        assert detail.icon == "Shield"
        assert detail.maturity == AgentMaturity.STABLE

    def test_skill_summary_and_detail_defaults(self):
        """Skill response schemas default taxonomy fields appropriately."""
        summary = SkillSummary(
            id="sum-skill",
            name="sum-skill",
            description="Skill summary",
        )
        assert summary.domain == AgentDomain.WELLNESS
        assert summary.category == ""
        assert summary.tags == []

        detail = SkillDetailResponse(
            id="det-skill",
            name="det-skill",
            description="Skill detail",
        )
        assert detail.domain == AgentDomain.WELLNESS
        assert detail.category == ""
        assert detail.tags == []

    def test_partial_taxonomy_fields_preserve_remaining_defaults(self):
        """Providing a subset of taxonomy fields must not overwrite unspecified defaults."""
        # Only domain provided
        agent1 = AgentManifest(
            id="agent-1",
            title="Agent 1",
            persona="Bot",
            domain=AgentDomain.THERAPY,
        )
        assert agent1.domain == AgentDomain.THERAPY
        assert agent1.category == ""
        assert agent1.care_stages == []
        assert agent1.target_audience == []
        assert agent1.tags == []
        assert agent1.icon == "Shield"
        assert agent1.maturity == AgentMaturity.STABLE

        # Only category and maturity provided
        agent2 = AgentManifest(
            id="agent-2",
            title="Agent 2",
            persona="Bot",
            category="clinical.pediatrics",
            maturity=AgentMaturity.BETA,
        )
        assert agent2.domain == AgentDomain.WELLNESS
        assert agent2.category == "clinical.pediatrics"
        assert agent2.care_stages == []
        assert agent2.target_audience == []
        assert agent2.tags == []
        assert agent2.icon == "Shield"
        assert agent2.maturity == AgentMaturity.BETA

        # Only care_stages and icon provided
        agent3 = AgentManifest(
            id="agent-3",
            title="Agent 3",
            persona="Bot",
            care_stages=["pre_visit", "during_visit"],
            icon="Stethoscope",
        )
        assert agent3.domain == AgentDomain.WELLNESS
        assert agent3.category == ""
        assert agent3.care_stages == ["pre_visit", "during_visit"]
        assert agent3.icon == "Stethoscope"
        assert agent3.maturity == AgentMaturity.STABLE

    def test_default_list_immutability_and_independence(self):
        """Ensure default lists do not share mutable references between instances."""
        agent_a = AgentManifest(id="agent-a", title="A", persona="Bot")
        agent_b = AgentManifest(id="agent-b", title="B", persona="Bot")

        agent_a.care_stages.append("daily_living")
        agent_a.target_audience.append("adult")
        agent_a.tags.append("urgent")

        assert agent_b.care_stages == []
        assert agent_b.target_audience == []
        assert agent_b.tags == []


# ============================================================================
# 3. Adversarial / Boundary Input Handling
# ============================================================================

class TestAdversarialInputs:
    """Stress tests boundary inputs, nulls, extra fields, and unicode."""

    def test_extra_fields_in_agent_manifest_and_responses(self):
        """Extra / unrecognized fields should not crash default schema validation."""
        payload: Dict[str, Any] = {
            "id": "extra-fields-agent",
            "title": "Extra Fields Agent",
            "persona": "Bot",
            "extra_taxonomy_score": 99.5,
            "random_field": {"nested": "data"},
        }
        agent = AgentManifest(**payload)
        assert agent.id == "extra-fields-agent"
        assert agent.domain == AgentDomain.WELLNESS

    @pytest.mark.parametrize(
        "null_field",
        ["domain", "maturity", "category", "tags", "care_stages", "target_audience", "icon"],
    )
    def test_explicit_null_in_non_nullable_fields_raises_validation_error(self, null_field: str):
        """Explicitly passing null (None) to non-optional fields must raise ValidationError."""
        payload: Dict[str, Any] = {
            "id": "null-test-agent",
            "title": "Null Test Agent",
            "persona": "Bot",
            null_field: None,
        }
        with pytest.raises(ValidationError) as exc_info:
            AgentManifest(**payload)
        assert null_field in str(exc_info.value)

    def test_carefold_yaml_nullable_fields_graceful_handling(self):
        """In CarefoldYaml, fields are Optional so None is accepted."""
        cf = CarefoldYaml(
            domain=None,
            category=None,
            tags=None,
        )
        assert cf.domain is None
        assert cf.category is None
        assert cf.tags is None

    def test_unicode_and_special_characters_in_taxonomy(self):
        """Taxonomy fields should gracefully preserve unicode and special characters."""
        unicode_tags = ["🏥-hospital", "pediatría", "🩺", "mental-health", "50%_discount"]
        unicode_category = "clínica.pediatría.alergología"

        agent = AgentManifest(
            id="unicode-agent",
            title="Unicode Agent",
            persona="Bot",
            category=unicode_category,
            tags=unicode_tags,
        )
        assert agent.category == unicode_category
        assert agent.tags == unicode_tags

    def test_long_string_category_and_large_tag_set(self):
        """Handles deep category nesting and high tag cardinality."""
        deep_category = ".".join([f"sub_{i}" for i in range(50)])
        large_tags = [f"tag-{i}" for i in range(200)]

        agent = AgentManifest(
            id="stress-agent",
            title="Stress Agent",
            persona="Bot",
            category=deep_category,
            tags=large_tags,
        )
        assert agent.category == deep_category
        assert len(agent.tags) == 200


# ============================================================================
# 4. JSON Serialization & Round-Trip Fidelity
# ============================================================================

class TestSerializationAndRoundTrip:
    """Verifies model_dump(), model_dump_json(), and deserialization round-trip."""

    def test_agent_manifest_round_trip(self):
        agent = AgentManifest(
            id="rt-agent",
            title="Roundtrip Agent",
            domain=AgentDomain.CLINICAL,
            category="clinical.cardiology",
            care_stages=["pre_visit", "during_visit"],
            target_audience=["patient_adult"],
            tags=["cardiology", "ecg"],
            icon="Heart",
            maturity=AgentMaturity.BETA,
            persona="Cardiologist assistant",
            can_delegate=True,
            max_iterations=5,
            description="Cardiology guide",
        )

        # 1. model_dump()
        dumped = agent.model_dump()
        assert dumped["domain"] == AgentDomain.CLINICAL
        assert dumped["maturity"] == AgentMaturity.BETA

        # 2. model_dump(mode='json')
        json_dumped = agent.model_dump(mode="json")
        assert json_dumped["domain"] == "clinical"
        assert json_dumped["maturity"] == "beta"
        assert isinstance(json_dumped["domain"], str)

        # 3. model_dump_json() and model_validate_json() round-trip
        json_str = agent.model_dump_json()
        assert '"domain":"clinical"' in json_str or '"domain": "clinical"' in json_str
        assert '"maturity":"beta"' in json_str or '"maturity": "beta"' in json_str

        reconstructed = AgentManifest.model_validate_json(json_str)
        assert reconstructed == agent
        assert reconstructed.domain == AgentDomain.CLINICAL
        assert reconstructed.maturity == AgentMaturity.BETA

    def test_skill_manifest_round_trip(self):
        skill = SkillManifest(
            id="rt-skill",
            name="rt-skill",
            description="Roundtrip skill",
            domain=AgentDomain.EDUCATION,
            category="education.asthma",
            tags=["inhaler", "asthma-action-plan"],
        )

        dumped_json = skill.model_dump_json()
        assert '"domain":"education"' in dumped_json or '"domain": "education"' in dumped_json
        assert '"category":"education.asthma"' in dumped_json or '"category": "education.asthma"' in dumped_json

        reconstructed = SkillManifest.model_validate_json(dumped_json)
        assert reconstructed == skill
        assert reconstructed.domain == AgentDomain.EDUCATION

    def test_agent_summary_and_detail_round_trip(self):
        summary = AgentSummary(
            id="rt-summary",
            title="RT Summary",
            domain=AgentDomain.NAVIGATION,
            category="navigation.insurance",
            care_stages=["post_visit"],
            target_audience=["parent_caregiver"],
            tags=["insurance", "claim"],
            icon="FileText",
            maturity=AgentMaturity.STABLE,
        )
        json_str = summary.model_dump_json()
        rec_summary = AgentSummary.model_validate_json(json_str)
        assert rec_summary == summary
        assert rec_summary.domain == AgentDomain.NAVIGATION
        assert rec_summary.maturity == AgentMaturity.STABLE

        detail = AgentDetailResponse(
            id="rt-detail",
            title="RT Detail",
            persona="Guide",
            personaSummary="Summary of guide",
            domain=AgentDomain.THERAPY,
            category="therapy.cbt",
            care_stages=["daily_living"],
            target_audience=["patient_adult"],
            tags=["cbt", "journal"],
            icon="Brain",
            maturity=AgentMaturity.DRAFT,
        )
        detail_json = detail.model_dump_json()
        rec_detail = AgentDetailResponse.model_validate_json(detail_json)
        assert rec_detail == detail
        assert rec_detail.domain == AgentDomain.THERAPY
        assert rec_detail.maturity == AgentMaturity.DRAFT

    def test_skill_summary_and_detail_round_trip(self):
        summary = SkillSummary(
            id="rt-skill-sum",
            name="rt-skill-sum",
            description="Skill summary",
            domain=AgentDomain.CLINICAL,
            category="clinical.triage",
            tags=["triage", "urgent"],
        )
        rec_sum = SkillSummary.model_validate_json(summary.model_dump_json())
        assert rec_sum == summary

        detail = SkillDetailResponse(
            id="rt-skill-det",
            name="rt-skill-det",
            description="Skill detail",
            domain=AgentDomain.WELLNESS,
            category="wellness.mindfulness",
            tags=["meditation"],
        )
        rec_det = SkillDetailResponse.model_validate_json(detail.model_dump_json())
        assert rec_det == detail


# ============================================================================
# 5. Loader Integration Stress Tests (File-System Level)
# ============================================================================

class TestLoaderIntegrationStress:
    """Stress tests load_agent and load_skill under adversarial filesystem scenarios."""

    def test_load_agent_yaml_inputs(self, tmp_path: Path):
        """Test agent loading with missing, partial, extra, and invalid YAML attributes."""
        # 1. Missing all taxonomy fields -> loads defaults
        dir1 = tmp_path / "agent-defaults"
        dir1.mkdir()
        (dir1 / "agent.yaml").write_text(
            """id: agent-defaults
title: Agent Defaults
persona: Persona text
""",
            encoding="utf-8",
        )
        agent1, _, _ = load_agent(dir1)
        assert agent1.domain == AgentDomain.WELLNESS
        assert agent1.category == ""
        assert agent1.care_stages == []
        assert agent1.target_audience == []
        assert agent1.tags == []
        assert agent1.icon == "Shield"
        assert agent1.maturity == AgentMaturity.STABLE

        # 2. Extra unexpected fields in agent.yaml -> successfully loads
        dir2 = tmp_path / "agent-extra"
        dir2.mkdir()
        (dir2 / "agent.yaml").write_text(
            """id: agent-extra
title: Agent Extra
persona: Persona text
unknown_taxonomy_setting: true
metadata_blob:
  custom_key: 12345
domain: education
""",
            encoding="utf-8",
        )
        agent2, _, _ = load_agent(dir2)
        assert agent2.domain == AgentDomain.EDUCATION
        assert agent2.icon == "Shield"

        # 3. Invalid domain enum in agent.yaml -> raises ManifestValidationError
        dir3 = tmp_path / "agent-bad-dom"
        dir3.mkdir()
        (dir3 / "agent.yaml").write_text(
            """id: agent-bad-dom
title: Agent Bad Dom
persona: Persona text
domain: non_existent_domain
""",
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError, match="domain"):
            load_agent(dir3)

        # 4. Invalid maturity enum in agent.yaml -> raises ManifestValidationError
        dir4 = tmp_path / "agent-bad-mat"
        dir4.mkdir()
        (dir4 / "agent.yaml").write_text(
            """id: agent-bad-mat
title: Agent Bad Mat
persona: Persona text
maturity: experimental
""",
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError, match="maturity"):
            load_agent(dir4)

        # 5. Null domain in agent.yaml -> raises ManifestValidationError
        dir5 = tmp_path / "agent-null-dom"
        dir5.mkdir()
        (dir5 / "agent.yaml").write_text(
            """id: agent-null-dom
title: Agent Null Dom
persona: Persona text
domain: null
""",
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError, match="domain"):
            load_agent(dir5)

    def test_load_skill_frontmatter_and_carefold_yaml(self, tmp_path: Path):
        """Test skill loading with various combinations of SKILL.md and carefold.yaml."""
        # 1. Frontmatter without carefold.yaml -> loads defaults
        s1_dir = tmp_path / "skill-fm-only"
        s1_dir.mkdir()
        (s1_dir / "SKILL.md").write_text(
            """---
name: skill-fm-only
description: FM only skill
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
            encoding="utf-8",
        )
        skill1 = load_skill(s1_dir)
        assert skill1.domain == AgentDomain.WELLNESS
        assert skill1.category == ""
        assert skill1.tags == []

        # 2. Invalid domain in SKILL.md frontmatter -> raises ManifestValidationError
        s2_dir = tmp_path / "skill-bad-fm-dom"
        s2_dir.mkdir()
        (s2_dir / "SKILL.md").write_text(
            """---
name: skill-bad-fm-dom
description: Bad FM domain
domain: invalid_domain_xyz
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError, match="domain"):
            load_skill(s2_dir)

        # 3. Invalid domain in carefold.yaml -> raises ManifestValidationError
        s3_dir = tmp_path / "skill-bad-cf-dom"
        s3_dir.mkdir()
        (s3_dir / "SKILL.md").write_text(
            """---
name: skill-bad-cf-dom
description: Good FM
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
            encoding="utf-8",
        )
        (s3_dir / "carefold.yaml").write_text(
            """id: skill-bad-cf-dom
domain: invalid_cf_domain
""",
            encoding="utf-8",
        )
        with pytest.raises(ManifestValidationError, match="domain"):
            load_skill(s3_dir)

        # 4. carefold.yaml with domain: null falls back to frontmatter / default
        s4_dir = tmp_path / "skill-null-cf-dom"
        s4_dir.mkdir()
        (s4_dir / "SKILL.md").write_text(
            """---
name: skill-null-cf-dom
description: Good FM
domain: therapy
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
            encoding="utf-8",
        )
        (s4_dir / "carefold.yaml").write_text(
            """id: skill-null-cf-dom
domain: null
category: null
tags: null
""",
            encoding="utf-8",
        )
        skill4 = load_skill(s4_dir)
        # cf.domain is None, so it falls back to fm.domain: therapy
        assert skill4.domain == AgentDomain.THERAPY
        assert skill4.category == ""
        assert skill4.tags == []

        # 5. Tag deduplication between carefold.yaml and SKILL.md
        s5_dir = tmp_path / "skill-dedup-tags"
        s5_dir.mkdir()
        (s5_dir / "SKILL.md").write_text(
            """---
name: skill-dedup-tags
description: Good FM
tags:
  - shared-tag
  - fm-tag
---
- Not a clinician and not emergency care
- If this is an emergency, contact local emergency services
- Do not change medication without the prescribing clinician
""",
            encoding="utf-8",
        )
        (s5_dir / "carefold.yaml").write_text(
            """id: skill-dedup-tags
tags:
  - cf-tag
  - shared-tag
""",
            encoding="utf-8",
        )
        skill5 = load_skill(s5_dir)
        assert skill5.tags == ["cf-tag", "shared-tag", "fm-tag"]


# ============================================================================
# 6. Real-World Workspace Manifest Audit
# ============================================================================

class TestWorkspaceManifestAudit:
    """Audits all real agent manifests currently in the repository."""

    def test_all_workspace_agents_taxonomy_fields(self):
        """Ensures every real agent in agents/ loads cleanly and has valid taxonomy."""
        from carefold.config import settings
        agents_dir = settings.get_agents_dir()
        skills_dir = settings.get_skills_dir()

        agents = load_all_agents(agents_dir, skills_dir)
        by_id = {a.id: a for a in agents}

        # 1. benefits-guide
        assert "benefits-guide" in by_id
        bg = by_id["benefits-guide"]
        assert bg.domain == AgentDomain.NAVIGATION
        assert bg.category == "navigation.insurance"
        assert set(bg.care_stages) == {"post_visit", "daily_living"}
        assert bg.icon == "FileText"
        assert bg.maturity == AgentMaturity.STABLE
        assert "insurance" in bg.tags
        assert "benefits" in bg.tags

        # 2. habit-companion
        assert "habit-companion" in by_id
        hc = by_id["habit-companion"]
        assert hc.domain == AgentDomain.WELLNESS
        assert hc.category == "wellness.habits"
        assert set(hc.care_stages) == {"daily_living"}
        assert hc.icon == "HeartPulse"
        assert hc.maturity == AgentMaturity.STABLE
        assert "habits" in hc.tags

        # 3. visit-steward
        assert "visit-steward" in by_id
        vs = by_id["visit-steward"]
        assert vs.domain == AgentDomain.NAVIGATION
        assert vs.category == "navigation.appointments"
        assert set(vs.care_stages) == {"pre_visit", "during_visit"}
        assert vs.icon == "Stethoscope"
        assert vs.maturity == AgentMaturity.STABLE
        assert "visit-prep" in vs.tags

        # 4. System agents without explicit taxonomy receive valid defaults
        system_agents = ["document-extractor", "orchestrator", "skill-generator", "suggestion-generator"]
        for sys_id in system_agents:
            if sys_id in by_id:
                sys_a = by_id[sys_id]
                assert sys_a.domain == AgentDomain.WELLNESS
                assert sys_a.category == ""
                assert sys_a.care_stages == []
                assert sys_a.target_audience == []
                assert sys_a.tags == []
                assert sys_a.icon == "Shield"
                assert sys_a.maturity == AgentMaturity.STABLE


# ============================================================================
# 7. HTTP API Endpoint Verification
# ============================================================================

class TestApiTaxonomyEndpoints:
    """Verifies that HTTP API responses serialize all taxonomy fields properly."""

    def test_api_list_agents_taxonomy_serialization(self, client):
        """GET /api/agents must return taxonomy fields on each agent summary."""
        resp = client.get("/api/agents?include_hidden=true")
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) > 0

        for agent in agents:
            assert "domain" in agent
            assert agent["domain"] in [d.value for d in AgentDomain]
            assert "category" in agent
            assert isinstance(agent["category"], str)
            assert "care_stages" in agent
            assert isinstance(agent["care_stages"], list)
            assert "target_audience" in agent
            assert isinstance(agent["target_audience"], list)
            assert "tags" in agent
            assert isinstance(agent["tags"], list)
            assert "icon" in agent
            assert isinstance(agent["icon"], str)
            assert "maturity" in agent
            assert agent["maturity"] in [m.value for m in AgentMaturity]

    def test_api_agent_detail_taxonomy_serialization(self, client):
        """GET /api/agents/{agent_id} returns all 7 taxonomy fields."""
        resp = client.get("/api/agents/benefits-guide")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "benefits-guide"
        assert data["domain"] == "navigation"
        assert data["category"] == "navigation.insurance"
        assert data["icon"] == "FileText"
        assert data["maturity"] == "stable"
        assert "post_visit" in data["care_stages"]
        assert "insurance" in data["tags"]

    def test_api_list_skills_taxonomy_serialization(self, client):
        """GET /api/skills must return taxonomy fields on each skill summary."""
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        skills = resp.json()
        assert len(skills) > 0

        for skill in skills:
            assert "domain" in skill
            assert skill["domain"] in [d.value for d in AgentDomain]
            assert "category" in skill
            assert isinstance(skill["category"], str)
            assert "tags" in skill
            assert isinstance(skill["tags"], list)

    def test_api_skill_detail_taxonomy_serialization(self, client):
        """GET /api/skills/{skill_id} returns taxonomy fields."""
        # Find an existing skill
        skills_resp = client.get("/api/skills")
        assert skills_resp.status_code == 200
        skills = skills_resp.json()
        if skills:
            first_skill = skills[0]
            resp = client.get(f"/api/skills/{first_skill['id']}")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == first_skill["id"]
            assert "domain" in data
            assert data["domain"] in [d.value for d in AgentDomain]
            assert "category" in data
            assert "tags" in data

