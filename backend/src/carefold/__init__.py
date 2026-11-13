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

"""Carefold — Local-first personal and family health AI companion & health domain pack."""

from __future__ import annotations

import os as _os

# yarvelle-core 0.2+ runtime identity / pack discovery (Carefold brand).
_os.environ.setdefault("YARVELLE_PACK_PACKAGES", "carefold")
_os.environ.setdefault("YARVELLE_APP_SLUG", "carefold")
_os.environ.setdefault("YARVELLE_LOCAL_DOMAIN", "carefold.local")
_os.environ.setdefault("YARVELLE_HOME_DIR_NAME", ".carefold")
_os.environ.setdefault("YARVELLE_DB_FILENAME", "carefold.db")
_os.environ.setdefault("YARVELLE_ENV_PREFIX", "CAREFOLD")
# Core vault identity: core derives the vault KEK (passphrase path) and the
# checkpoint key (HKDF salt) from <PREFIX>_VAULT_SALT. Existing Carefold vaults
# use carefold.vault.kek.DEFAULT_ARGON2_SALT (pinned by tests/test_vault_salt_pin.py),
# so core must use the same salt. An explicit CAREFOLD_VAULT_SALT still wins.
_os.environ.setdefault("YARVELLE_VAULT_SALT", "carefold_kek_sal")

# Align yarvelle-core public brand settings with Carefold (skill-docs / ICS / prompts).
try:
    from yarvelle_core.config import settings as _yc_settings

    _yc_settings.brand_config.product_name = "Carefold"
    _yc_settings.brand_config.env_prefix = "CAREFOLD_"
    _yc_settings.brand_config.home_dir_name = ".carefold"
    _yc_settings.brand_config.db_filename = "carefold.db"
    _yc_settings.brand_config.oauth_scheme = "carefold"
    _yc_settings.brand_config.cookie_prefix = "carefold_"
    _yc_settings.brand_config.default_agent = "appointment-prep-coordinator"
    # CAREFOLD_CHECKPOINT_* aliases for core checkpoint encryption settings.
    from carefold.checkpoint_env import apply_checkpoint_encryption_default as _apply_cp_default
    from carefold.checkpoint_env import apply_checkpoint_env_aliases as _apply_cp_aliases

    _apply_cp_aliases(_os.environ, _yc_settings)
    # Checkpoints are encrypted at rest by default (explicit settings win).
    _apply_cp_default(_os.environ, _yc_settings)
except Exception:
    pass


import logging
from pathlib import Path
from typing import Any, List

from yarvelle_core.pack.spec import PackEvalsSpec, PackProvidesSpec, PackSpec, RouterContribution
from yarvelle_core.schemas.orchestration import (
    DelegationReminderSpec,
    DelegationSpec,
    FixedRoute,
    HasAttachmentsTrigger,
    OrchestrationLimits,
    PackOrchestrationSpec,
    SynthesisSpec,
)
from yarvelle_core.schemas.routing import RoutingHints
from yarvelle_core.schemas.safety import GuardCheckSpec, PackSafetySpec, SafetyGuardsSpec
from yarvelle_core.workflows.subgraphs.extraction.dossiers import register_dossier_type

try:
    from carefold.auth_reset import install_atomic_password_reset as _install_atomic_password_reset

    _install_atomic_password_reset()
except Exception:
    pass

logger = logging.getLogger("carefold")

__version__ = "0.5.0b2"

# Eagerly register "clinical" on core AgentDomain, dual-version RiskClass, and Carefold locale catalog
try:
    import yarvelle_core.i18n.catalog as _yc_catalog
    from yarvelle_core.schemas.manifest import AgentDomain, RiskClass

    _yc_catalog.LOCALES_DIR = Path(__file__).resolve().parent / "resources" / "locales"
    if hasattr(AgentDomain, "register") and not hasattr(AgentDomain, "CLINICAL"):
        AgentDomain.CLINICAL = AgentDomain.register("clinical")
    if hasattr(RiskClass, "register") and not hasattr(RiskClass, "ASSIST"):
        RiskClass.ASSIST = RiskClass.register("assist")
    if hasattr(RiskClass, "register") and not hasattr(RiskClass, "CLINICAL_ASSIST"):
        RiskClass.CLINICAL_ASSIST = RiskClass.register("clinical_assist")
except Exception:
    pass

# Eagerly register health reminder categories
try:
    from yarvelle_core.tools.reminders import register_reminder_category

    for _cat in ("medication", "vitals", "appointment"):
        register_reminder_category(_cat)
except Exception:
    pass

# Eagerly register health dossiers into yarvelle_core extraction registry
try:
    from carefold.dossiers import (
        ClinicalVisitDossier,
        InsuranceBenefitsDossier,
    )

    register_dossier_type("clinical_visit", ClinicalVisitDossier)
    register_dossier_type("clinical", ClinicalVisitDossier)
    register_dossier_type("insurance_benefits", InsuranceBenefitsDossier)
    register_dossier_type("insurance", InsuranceBenefitsDossier)

    from carefold.clinical.dossier_heuristics import register_carefold_dossier_heuristics

    register_carefold_dossier_heuristics()
except Exception:
    pass




def _build_pack_provides_spec(**kwargs: Any) -> PackProvidesSpec:
    """Constructs PackProvidesSpec, omitting unreleased fields on older yarvelle-core."""
    if "errors_file" in kwargs and "errors_file" not in PackProvidesSpec.model_fields:
        kwargs = {k: v for k, v in kwargs.items() if k != "errors_file"}
    return PackProvidesSpec(**kwargs)


def _build_pack_spec(**kwargs: Any) -> PackSpec:
    """Constructs PackSpec, passing error_prefix only when supported by installed yarvelle-core."""
    if "error_prefix" in kwargs and "error_prefix" not in PackSpec.model_fields:
        kwargs = {k: v for k, v in kwargs.items() if k != "error_prefix"}
    return PackSpec(**kwargs)


def get_pack() -> PackSpec:
    """Pack factory discovered by yarvelle_core via entry point 'yarvelle.packs'.

    Returns:
        PackSpec: Populated and validated specification of the health pack.
    """
    # 1. Register domain dossiers into the yarvelle_core extraction registry
    from carefold.dossiers import (
        ClinicalVisitDossier,
        InsuranceBenefitsDossier,
    )
    register_dossier_type("clinical_visit", ClinicalVisitDossier)
    register_dossier_type("clinical", ClinicalVisitDossier)
    register_dossier_type("insurance_benefits", InsuranceBenefitsDossier)
    register_dossier_type("insurance", InsuranceBenefitsDossier)

    # 2. Safety policy instance
    from carefold.safety import CarefoldHealthSafetyPolicy
    safety_policy = CarefoldHealthSafetyPolicy()

    # 3. Health ToolSpecs (17 tools)
    from carefold.tools import get_health_tool_specs
    tools = get_health_tool_specs()

    # 4. Health Routers (9 routers)
    from carefold.routers import get_health_router_contributions
    routers: List[RouterContribution] = get_health_router_contributions()

    # 5. Scoped ORM Models (7 models)
    from carefold.models import (
        Appointment,
        CompanionDevice,
        HealthResource,
        ImportBatch,
        PreventiveRecord,
        SchoolForm,
        SchoolIcsFeed,
    )
    scoped_models = [
        HealthResource,
        Appointment,
        PreventiveRecord,
        ImportBatch,
        SchoolForm,
        SchoolIcsFeed,
        CompanionDevice,
    ]

    # 6. Routing hints
    routing_hints = RoutingHints(
        domain="health",
        description="Clinical visit preparation, health records management, and insurance navigation",
        default_agent="appointment-prep-coordinator",
        patterns_resource="resources/routing_patterns.yaml",
    )

    # 7. Orchestration (pack.yaml orchestration twin)
    synthesis_path = Path(__file__).resolve().parent / "resources" / "prompts" / "orchestrator" / "synthesis.md"
    synthesis_instructions = synthesis_path.read_text(encoding="utf-8").strip()
    delegation_instructions = (synthesis_path.parent / "delegation.md").read_text(encoding="utf-8").strip()
    delegation_reminder = (synthesis_path.parent / "delegation_reminder.md").read_text(encoding="utf-8").strip()
    orchestration = PackOrchestrationSpec(
        default_agent="appointment-prep-coordinator",
        limits=OrchestrationLimits(
            max_agents=4,
            agent_timeout_s=60.0,
            turn_timeout_s=120.0,
        ),
        fixed_routes=[
            FixedRoute(
                route_id="document-intake",
                when=HasAttachmentsTrigger(
                    mime_types=["application/pdf", "image/*", "text/plain"],
                ),
                agent_id="document-extractor",
                description="Uploaded documents go to the document extractor.",
            ),
            # No red-flag route: the input guardrail answers an emergency with
            # the vetted referral before routing, and triage-auditor output is
            # internal audit text that must never reach the user.
        ],
        # Follow-up reminder: local models stop delegating once the chat has
        # history; core adds this to the model's copy of the latest user message.
        delegation=DelegationSpec(
            instructions=delegation_instructions,
            reminder=DelegationReminderSpec(when="follow_up", text=delegation_reminder),
        ),
        synthesis=SynthesisSpec(instructions=synthesis_instructions),
    )

    # 8. Safety guards (pack.yaml safety.guards twin)
    safety = PackSafetySpec(
        guards=SafetyGuardsSpec(
            release="buffered",
            checks=[
                GuardCheckSpec(
                    id="granite-guardian",
                    type="model",
                    preset="granite_guardian",
                    stages=["output"],
                    mode="shadow",
                    when_unconfigured="allow",
                ),
            ],
        ),
    )

    # 9. Evals spec
    evals = PackEvalsSpec(
        golden_path="evals/golden.jsonl",
        min_pass_rate=0.95,
        eval_suites=["clinical_safety", "emergency_red_flags", "boundary_enforcement"],
    )

    provides = _build_pack_provides_spec(
        prompts_dir="resources/prompts/",
        locales_dir="resources/locales/",
        connectors_dir="connectors/",
        resources_dir="resources/",
        workflows_dir="workflows/",
        errors_file="resources/errors.yaml",
    )

    spec = _build_pack_spec(
        pack_api=1,
        id="health",
        name="Carefold Health Pack",
        version=__version__,
        domain="health",
        requires_core=">=0.2.5,<0.3.0",
        owned_scopes=["health.*", "health.clinical", "health.paperwork"],
        declared_reads=[],
        risk_tier_max="T4",
        tools=tools,
        routers=routers,
        safety_policy=safety_policy,
        migration_branch="health",
        evals=evals,
        description="Family health, visit preparation, clinical records, and insurance navigation pack",
        license="PolyForm-Noncommercial-1.0.0 + Carefold Additional Terms",
        maintainers=["spectrayan/carefold-maintainers"],
        routing_hints=routing_hints,
        manifest_path=str(Path(__file__).resolve().parent / "pack.yaml"),
        scoped_models=scoped_models,
        provides=provides,
        orchestration=orchestration,
        safety=safety,
        error_prefix="CFD",
    )
    return spec


def _register_native_pack_resources() -> None:
    """Register Carefold's pack root, prompt templates, error catalog, and routing patterns with core.

    Uses a lightweight bootstrap ``PackSpec`` so ``carefold.middleware.skills`` and
    other modules imported transitively by ``get_pack()`` can resolve ``pack_id="health"``
    Handlebars templates without re-entrant import ordering issues.
    """
    from yarvelle_core.resources.loader import get_resource_loader as _yc_get_resource_loader

    bootstrap_spec = _build_pack_spec(
        pack_api=1,
        id="health",
        name="Carefold Health Pack",
        version=__version__,
        domain="health",
        requires_core=">=0.2.5,<0.3.0",
        routing_hints=RoutingHints(
            domain="health",
            description="Clinical visit preparation, health records management, and insurance navigation",
            default_agent="appointment-prep-coordinator",
            patterns_resource="resources/routing_patterns.yaml",
        ),
        manifest_path=str(Path(__file__).resolve().parent / "pack.yaml"),
        provides=_build_pack_provides_spec(
            prompts_dir="resources/prompts/",
            locales_dir="resources/locales/",
            connectors_dir="connectors/",
            resources_dir="resources/",
            workflows_dir="workflows/",
            errors_file="resources/errors.yaml",
        ),
        error_prefix="CFD",
    )
    _yc_get_resource_loader().register_pack(bootstrap_spec)
    try:
        from carefold.errors import register_carefold_error_catalog as _register_cfd_errors

        _register_cfd_errors()
    except Exception:
        pass
    try:
        from yarvelle_core.tools.spec_loader import register_pack_tool_manifest as _yc_register_pack_tools

        _tools_dir = Path(__file__).resolve().parent / "resources" / "tools"
        if _tools_dir.is_dir():
            _yc_register_pack_tools("health", _tools_dir)
    except Exception:
        pass


_register_native_pack_resources()

# Register CarefoldHealthSafetyPolicy via yarvelle_core's public safety policy registry
try:
    from yarvelle_core.engine.safety_policy import (
        set_default_safety_policy as _set_default_safety_policy,
        set_domain_safety_policy as _set_domain_safety_policy,
    )
    from carefold.safety import CarefoldHealthSafetyPolicy as _CarefoldHealthSafetyPolicy

    _default_health_policy = _CarefoldHealthSafetyPolicy()
    _set_default_safety_policy(_default_health_policy)
    _set_domain_safety_policy("clinical", _default_health_policy)
    _set_domain_safety_policy("health", _default_health_policy)
except Exception:
    pass

# Wire Carefold's agent/skill loaders onto yarvelle_core.db.seeding so SQL seeding
# preserves care_stages extensions and legacy carefold.yaml skill manifests.
try:
    import yarvelle_core.db.seeding as _yc_seeding
    from carefold.clinical.host_bridges import load_all_skills_compat as _load_all_skills_compat
    from carefold.loaders.agent_loader import (
        load_agent as _carefold_load_agent,
        load_all_agents as _carefold_load_all_agents,
    )

    _yc_seeding.load_agent = _carefold_load_agent
    _yc_seeding.load_all_agents = _carefold_load_all_agents
    _yc_seeding.load_all_skills = _load_all_skills_compat
except Exception:
    pass

__all__ = ["get_pack", "__version__"]
