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

"""Re-export shim delegating to yarvelle_core.workflows.subgraphs.extraction.dossiers."""

from __future__ import annotations

import sys

from yarvelle_core.workflows.subgraphs.extraction.dossiers import *  # noqa: F401, F403
from yarvelle_core.workflows.subgraphs.extraction.dossiers import register_dossier_type
import yarvelle_core.workflows.subgraphs.extraction.dossiers as _target_module

from carefold.dossiers import ClinicalVisitDossier, InsuranceBenefitsDossier

register_dossier_type("clinical_visit", ClinicalVisitDossier)
register_dossier_type("clinical", ClinicalVisitDossier)
register_dossier_type("insurance_benefits", InsuranceBenefitsDossier)
register_dossier_type("insurance", InsuranceBenefitsDossier)

setattr(_target_module, "ClinicalVisitDossier", ClinicalVisitDossier)
setattr(_target_module, "InsuranceBenefitsDossier", InsuranceBenefitsDossier)

sys.modules[__name__] = _target_module
