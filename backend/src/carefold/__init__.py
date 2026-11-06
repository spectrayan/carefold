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
_os.environ.setdefault("YARVELLE_ENV_PREFIX", "CAREFOLD")

# Align yarvelle-core settings brand with Carefold (skill-docs / ICS / prompts).
try:
    from yarvelle_core.config import BrandConfig as _YcBrandConfig
    from yarvelle_core.config import settings as _yc_settings

    _yc_settings._brand_config = _YcBrandConfig(
        product_name="Carefold",
        env_prefix="CAREFOLD_",
        home_dir_name=".carefold",
        default_agent="appointment-prep-coordinator",
    )
    # CAREFOLD_CHECKPOINT_* aliases for core checkpoint encryption settings.
    from carefold.checkpoint_env import apply_checkpoint_env_aliases as _apply_cp_aliases

    _apply_cp_aliases(_os.environ, _yc_settings)
except Exception:
    pass

# Inject Carefold routing dossier_types into yarvelle-core ResourceLoader so
# extraction subgraph auto-inference sees insurance/clinical patterns (core's
# packaged routing_patterns.yaml only knows generic; pack patterns_path is
# consumed for orchestrator hints, not the extraction loader).
try:
    from yarvelle_core.resources.loader import get_resource_loader as _yc_get_resource_loader

    from carefold.resources.loader import get_resource_loader as _cf_get_resource_loader

    _yc_loader = _yc_get_resource_loader()
    _cf_patterns = _cf_get_resource_loader().get_routing_patterns()
    _merged = dict(_yc_loader.get_routing_patterns())
    if isinstance(_cf_patterns.get("dossier_types"), dict):
        _merged["dossier_types"] = dict(_cf_patterns["dossier_types"])
    # Prefer Carefold agent routing keys when present
    for _k, _v in _cf_patterns.items():
        if _k == "dossier_types":
            continue
        if _k not in _merged or not _merged.get(_k):
            _merged[_k] = _v
    _yc_loader._cache["routing_patterns.yaml"] = _merged
except Exception:
    pass

import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.machinery as _machinery
import sys as _sys
from typing import Any

# Register `carefold_health` alias pointing directly to `carefold`
_sys.modules.setdefault("carefold_health", _sys.modules[__name__])


class _CarefoldAliasLoader(_importlib_abc.Loader):
    def __init__(self, target_mod: Any) -> None:
        self.target_mod = target_mod
        self.orig_spec = getattr(target_mod, "__spec__", None)

    def create_module(self, spec):
        return self.target_mod

    def exec_module(self, module):
        if self.orig_spec is not None:
            try:
                module.__spec__ = self.orig_spec
            except AttributeError:
                pass


_CORE_DELEGATED_SUBPACKAGES = (
    "auth",
    "memory",
    "scope",
    "settings",
)


class _CarefoldRedirectFinder(_importlib_abc.MetaPathFinder):
    """Redirects `carefold_health.*` to `carefold.*` and pure core subpackages to `yarvelle_core.*`."""

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname == "carefold_health" or fullname.startswith("carefold_health."):
            suffix = fullname[len("carefold_health"):]
            if suffix == ".db.models":
                target_name = "carefold.models.health"
            elif suffix == ".db.migrations" or suffix.startswith(".db.migrations."):
                target_name = "carefold.db.health_migrations" + suffix[len(".db.migrations"):]
            else:
                target_name = "carefold" + suffix
            try:
                mod = _importlib.import_module(target_name)
            except ImportError:
                return None
            is_pkg = hasattr(mod, "__path__")
            spec = _machinery.ModuleSpec(fullname, _CarefoldAliasLoader(mod), is_package=is_pkg)
            if is_pkg:
                spec.submodule_search_locations = list(mod.__path__)
            return spec

        for sub in _CORE_DELEGATED_SUBPACKAGES:
            prefix = f"carefold.{sub}"
            if fullname == prefix or fullname.startswith(prefix + "."):
                target_name = "yarvelle_core." + fullname[len("carefold."):]
                try:
                    mod = _importlib.import_module(target_name)
                except ImportError:
                    return None
                is_pkg = hasattr(mod, "__path__")
                spec = _machinery.ModuleSpec(fullname, _CarefoldAliasLoader(mod), is_package=is_pkg)
                if is_pkg:
                    spec.submodule_search_locations = list(mod.__path__)
                return spec
        return None



if not any(type(f).__name__ == "_CarefoldRedirectFinder" for f in _sys.meta_path):
    _sys.meta_path.insert(0, _CarefoldRedirectFinder())


import logging
from pathlib import Path
from typing import List

from yarvelle_core.pack.spec import PackEvalsSpec, PackSpec, RouterContribution
from yarvelle_core.schemas.orchestration import (
    FixedRoute,
    GuardrailFlagTrigger,
    HasAttachmentsTrigger,
    OrchestrationLimits,
    PackOrchestrationSpec,
    SynthesisSpec,
)
from yarvelle_core.schemas.routing import RoutingHints
from yarvelle_core.workflows.subgraphs.extraction.dossiers import register_dossier_type

try:
    import yarvelle_core.engine.tool_exec as _core_tool_exec
    from yarvelle_core.connectors.base import (
        ToolContext as _ConnectorToolContext,
        ToolSpec as _ConnectorToolSpec,
    )

    _core_tool_exec.ConnectorToolContext = _ConnectorToolContext
    _core_tool_exec.ConnectorToolSpec = _ConnectorToolSpec
except Exception:
    pass

logger = logging.getLogger("carefold_health")

__version__ = "0.5.0b2"

# Eagerly register "clinical" on core AgentDomain when health pack is loaded
try:
    from yarvelle_core.schemas.manifest import AgentDomain

    if hasattr(AgentDomain, "register") and not hasattr(AgentDomain, "CLINICAL"):
        AgentDomain.CLINICAL = AgentDomain.register("clinical")
except Exception:
    pass

# Eagerly register health reminder categories
try:
    from yarvelle_core.tools.reminders import register_reminder_category

    register_reminder_category("vitals")
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

    from yarvelle_core.workflows.subgraphs.extraction.tool import register_heuristic_extractor
    import re

    def _extract_clinical_visit_heuristic(text: str, dossier_cls: Any) -> Any:
        m_reason = re.search(r"reason\s*for\s*visit\s*:\s*([^\n\.]+)", text, re.I)
        reason = m_reason.group(1).strip() if m_reason else ""
        m_time = re.search(
            r"follow[- ]up\s*(?:is|:)?\s*(?:return\s*in\s*)?(\d+\s*(?:weeks?|days?|months?))",
            text,
            re.I,
        )
        timeline = m_time.group(1) if m_time else ""
        instructions = []
        m_inst = re.search(r"physician\s*instructions\s*:\s*([^\n]+)", text, re.I)
        if m_inst:
            raw_inst = [s.strip() for s in m_inst.group(1).split(",") if s.strip()]
            if raw_inst:
                instructions = raw_inst
        questions = []
        m_q = re.search(r"questions?\s*(?:to\s*ask)?\s*:\s*([^\n]+)", text, re.I)
        if m_q:
            raw_q = [s.strip() for s in m_q.group(1).split(",") if s.strip()]
            if raw_q:
                questions = raw_q
        return dossier_cls(
            reason_for_visit=reason,
            physician_instructions=instructions,
            follow_up_timeline=timeline,
            questions_to_ask=questions,
        )

    def _extract_insurance_benefits_heuristic(text: str, dossier_cls: Any) -> Any:
        m_ded = re.search(r"deductible\s*(?:is|:)?\s*(\$?\d+(?:,\d{3})*)", text, re.I)
        deductible = m_ded.group(1) if m_ded else ""
        if deductible and not deductible.startswith("$") and deductible.isdigit():
            deductible = f"${deductible}"
        copays: dict[str, str] = {}
        m_pc = re.search(r"primary\s*care\s*(?:visit)?(?:\s*copay)?(?:\s*[:is]+)?\s*(\$?\d+)", text, re.I)
        if m_pc:
            copays["primary_care"] = m_pc.group(1) if m_pc.group(1).startswith("$") else f"${m_pc.group(1)}"
        m_sp = re.search(r"specialist\s*(?:visit)?(?:\s*copay)?(?:\s*[:is]+)?\s*(\$?\d+)", text, re.I)
        if m_sp:
            copays["specialist"] = m_sp.group(1) if m_sp.group(1).startswith("$") else f"${m_sp.group(1)}"
        if not copays:
            m_gen_copay = re.search(r"copay\s*(?:is|:)?\s*(\$?\d+)", text, re.I)
            if m_gen_copay:
                val = m_gen_copay.group(1)
                copays["office_visit"] = val if val.startswith("$") else f"${val}"
        m_coin = re.search(r"coinsurance\s*(?:is|:)?\s*(\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*percent)", text, re.I)
        coinsurance = m_coin.group(1) if m_coin else ""
        m_oop = re.search(r"out[- ]of[- ]pocket\s*max(?:imum)?\s*(?:is|:)?\s*(\$?\d+(?:,\d{3})*)", text, re.I)
        oop = m_oop.group(1) if m_oop else ""
        m_rules = re.search(r"([^\n]*in-network[^\n]*)", text, re.I)
        rules = m_rules.group(1).strip() if m_rules else ""
        prior_auth = []
        if re.search(r"\bMRI\b", text):
            prior_auth.append("MRI")
        if re.search(r"\bCT\b", text):
            prior_auth.append("CT")
        if re.search(r"\bPET\b", text):
            prior_auth.append("PET")
        if re.search(r"\bphysical\s*therapy\b", text, re.I):
            prior_auth.append("physical therapy")
        return dossier_cls(
            deductible=deductible,
            copays=copays,
            coinsurance=coinsurance,
            out_of_pocket_maximum=oop,
            in_out_network_rules=rules,
            prior_authorization_flags=prior_auth,
        )

    register_heuristic_extractor("clinical_visit", _extract_clinical_visit_heuristic)
    register_heuristic_extractor("clinical", _extract_clinical_visit_heuristic)
    register_heuristic_extractor("ClinicalVisitDossier", _extract_clinical_visit_heuristic)
    register_heuristic_extractor("insurance_benefits", _extract_insurance_benefits_heuristic)
    register_heuristic_extractor("insurance", _extract_insurance_benefits_heuristic)
    register_heuristic_extractor("InsuranceBenefitsDossier", _extract_insurance_benefits_heuristic)
except Exception:
    pass




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
            FixedRoute(
                route_id="red-flag-escalation",
                when=GuardrailFlagTrigger(flag="red_flag"),
                agent_id="triage-auditor",
                description="Guardrail red-flag signals go to the triage auditor.",
            ),
        ],
        synthesis=SynthesisSpec(instructions=synthesis_instructions),
    )

    # 8. Evals spec
    evals = PackEvalsSpec(
        golden_path="evals/golden.jsonl",
        min_pass_rate=0.95,
        eval_suites=["clinical_safety", "emergency_red_flags", "boundary_enforcement"],
    )

    spec = PackSpec(
        pack_api=1,
        id="health",
        name="Carefold Health Pack",
        version=__version__,
        domain="health",
        requires_core=">=0.2.0,<0.3.0",
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
        scoped_models=scoped_models,
        orchestration=orchestration,
    )
    return spec


__all__ = ["get_pack", "__version__"]
