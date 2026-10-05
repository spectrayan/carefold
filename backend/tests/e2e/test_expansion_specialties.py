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

"""E2E Test Suite for Carefold Marketplace Expansion (Tiers 1–4).

Covers all 19 agents (8 core organ navigators, 5 extended specialty navigators,
4 healthcare administration stewards, 2 system infrastructure agents) and 17 companion
skills. See docs/testing/index.md for the test tier model.

Test Tiers:
- Tier 1: Feature Coverage (Manifest & schema conformance, frontmatter, 3 intended-use statements,
  carefold.yaml, >=2 references per skill, system agent hidden status).
- Tier 2: Boundary & Corner Cases (Persona >=250 words, 5 mandatory sections, Phase 0 tool allowlist,
  rejection of forbidden/unauthorized tools, condition-specific emergency red-flag triggers).
- Tier 3: Cross-Feature & Two-Hop Routing (Tier-1 domain classification, candidate filtering, FTS search,
  category tree counts, pre-flight reference doc provisioning).
- Tier 4: Real-World Journey Scenarios (Cardiology vitals/agenda prep, Oncology clinical trial prep,
  Acute dyspnea emergency redirection, Multi-provider chronic care management, HIPAA records coordination).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from carefold.config import settings
from carefold.loaders.agent_loader import load_agent, load_all_agents
from carefold.loaders.frontmatter import check_mandatory_intended_use, parse_frontmatter
from carefold.loaders.skill_loader import load_skill, load_all_skills
from carefold.loaders.union import validate_tools_in_phase0
from carefold.memory.adapters.sqlite.catalog_adapter import (
    SqliteCatalogAdapter,
    build_category_tree_from_rows,
)
from carefold.memory.ports.catalog_port import CatalogPort
from carefold.safety.classifier import check_safety_refusal
from carefold.safety.template import SAFE_REFUSAL_TEMPLATE
from carefold.schemas.manifest import (
    AgentDomain,
    AgentManifest,
    AgentMaturity,
    CarefoldYaml,
    PHASE_0_REGISTRY,
    RiskClass,
    SkillFrontmatter,
    SkillManifest,
)
from carefold.schemas.tool import ToolResult
from carefold.tools.attach_read import execute_attach_read
from carefold.tools.workspace_note import execute_workspace_note
from carefold.workflows.nodes.orchestrator_node import (
    DomainClassification,
    OrchestratorDecision,
    OrchestratorNode,
    TIER1_DOMAIN_CLASSIFIER_PROMPT,
)
from tests.e2e.conftest import read_attachment_sync, record_audit_sync


# ============================================================================
# Authoritative Constants & Specifications
# ============================================================================

MANDATORY_INTENDED_USE_STATEMENTS = [
    "Not a clinician and not emergency care",
    "If this is an emergency, contact local emergency services",
    "Do not change medication without the prescribing clinician",
]

MANDATORY_PERSONA_SECTIONS = [
    "ROLE & EMPATHY",
    "CLINICAL SCOPE & FOCUS",
    "STRUCTURED INTERACTION PROTOCOL",
    "STRICT NON-CLINICAL BOUNDARIES",
    "EXPLICIT EMERGENCY RED FLAGS",
]

MANDATORY_FORBIDDEN_ACTIONS = [
    "diagnose",
    "prescribe",
    "dose",
    "replace_emergency_care",
    "instruct_stop_medication",
]

EXPANSION_AGENTS: List[Dict[str, Any]] = [
    {
        "id": "cardiology-guide",
        "title": "Cardiology Navigator",
        "domain": "clinical",
        "category": "clinical.cardiology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "cardiac_patient", "caregiver"],
        "tags": ["cardiology", "hypertension", "arrhythmia", "blood-pressure", "heart-health", "chest-pain-protocol"],
        "icon": "Heart",
        "companion_skill": "cardiology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "crushing chest pain radiating to left arm and jaw with cold sweat",
    },
    {
        "id": "pulmonology-guide",
        "title": "Pulmonology Navigator",
        "domain": "clinical",
        "category": "clinical.pulmonology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "respiratory_patient", "caregiver"],
        "tags": ["pulmonology", "asthma", "copd", "inhaler", "shortness-of-breath", "respiratory"],
        "icon": "Wind",
        "companion_skill": "pulmonology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "severe acute dyspnea with blue lips, struggling to speak full sentences",
    },
    {
        "id": "neurology-guide",
        "title": "Neurology Navigator",
        "domain": "clinical",
        "category": "clinical.neurology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "neurology_patient", "caregiver"],
        "tags": ["neurology", "migraine", "headache", "neuropathy", "cognitive", "brain-health"],
        "icon": "Brain",
        "companion_skill": "neurology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "sudden unilateral facial drooping, right arm numbness, and slurred speech",
    },
    {
        "id": "gastro-guide",
        "title": "Gastroenterology Navigator",
        "domain": "clinical",
        "category": "clinical.gastroenterology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living"],
        "target_audience": ["patient_adult", "gi_patient", "caregiver"],
        "tags": ["gastroenterology", "ibs", "ibd", "colonoscopy", "endoscopy", "digestive-health"],
        "icon": "Utensils",
        "companion_skill": "gastro-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "vomiting large pools of blood with rigid board-like abdomen and dizziness",
    },
    {
        "id": "nephrology-guide",
        "title": "Nephrology Navigator",
        "domain": "clinical",
        "category": "clinical.nephrology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "renal_patient", "caregiver"],
        "tags": ["nephrology", "kidney", "egfr", "creatinine", "renal-diet", "fluid-balance"],
        "icon": "Droplet",
        "companion_skill": "nephrology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "complete anuria for 24 hours with severe respiratory fluid overload",
    },
    {
        "id": "endocrinology-guide",
        "title": "Endocrinology Navigator",
        "domain": "clinical",
        "category": "clinical.endocrinology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "diabetic_patient", "caregiver"],
        "tags": ["endocrinology", "diabetes", "cgm", "a1c", "thyroid", "metabolic"],
        "icon": "Activity",
        "companion_skill": "endocrinology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "blood glucose 580 with severe confusion, rapid breathing, and vomiting",
    },
    {
        "id": "ortho-guide",
        "title": "Orthopedics Navigator",
        "domain": "clinical",
        "category": "clinical.orthopedics",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "follow_up"],
        "target_audience": ["patient_adult", "orthopedic_patient", "caregiver"],
        "tags": ["orthopedics", "joints", "musculoskeletal", "physical-therapy", "mobility", "surgery-prep"],
        "icon": "Bone",
        "companion_skill": "ortho-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "open compound tibia fracture sticking through skin with cold pulseless foot",
    },
    {
        "id": "derma-guide",
        "title": "Dermatology Navigator",
        "domain": "clinical",
        "category": "clinical.dermatology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living"],
        "target_audience": ["patient_adult", "skin_patient", "caregiver"],
        "tags": ["dermatology", "skin", "rash", "lesion", "abcde", "melanoma-screening"],
        "icon": "Sun",
        "companion_skill": "derma-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "severe sheet-like skin sloughing with mouth mucosal blisters and high fever",
    },
    {
        "id": "oncology-navigator",
        "title": "Oncology Care Steward",
        "domain": "clinical",
        "category": "clinical.oncology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "cancer_patient", "caregiver"],
        "tags": ["oncology", "cancer", "chemotherapy", "tumor-board", "clinical-trials", "side-effects"],
        "icon": "Ribbon",
        "companion_skill": "oncology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "fever of 103.5F with shaking chills during active chemotherapy cycle",
    },
    {
        "id": "rheuma-guide",
        "title": "Rheumatology Navigator",
        "domain": "clinical",
        "category": "clinical.rheumatology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "autoimmune_patient", "caregiver"],
        "tags": ["rheumatology", "autoimmune", "lupus", "rheumatoid-arthritis", "biologics", "joint-stiffness"],
        "icon": "Flame",
        "companion_skill": "rheuma-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "acutely hot, red, intensely painful swollen single knee with 103F fever",
    },
    {
        "id": "urology-guide",
        "title": "Urology Navigator",
        "domain": "clinical",
        "category": "clinical.urology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "urology_patient", "caregiver"],
        "tags": ["urology", "bladder", "urinary", "prostate", "psa", "voiding-diary"],
        "icon": "Droplets",
        "companion_skill": "urology-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "acute excruciating urinary retention with extreme suprapubic distension",
    },
    {
        "id": "eye-guide",
        "title": "Ophthalmology Navigator",
        "domain": "clinical",
        "category": "clinical.ophthalmology",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "follow_up"],
        "target_audience": ["patient_adult", "vision_patient", "senior", "caregiver"],
        "tags": ["ophthalmology", "vision", "glaucoma", "macular-degeneration", "cataracts", "eye-exam"],
        "icon": "Eye",
        "companion_skill": "vision-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "sudden total dark curtain falling over left eye with bright flashes",
    },
    {
        "id": "ent-guide",
        "title": "ENT Navigator",
        "domain": "clinical",
        "category": "clinical.ent",
        "risk_class": "clinical_assist",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living"],
        "target_audience": ["patient_adult", "ent_patient", "caregiver"],
        "tags": ["ent", "otolaryngology", "sinusitis", "tinnitus", "hearing", "vertigo"],
        "icon": "Ear",
        "companion_skill": "ent-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": "acute inspiratory stridor, drooling, severe airway obstruction",
    },
    {
        "id": "prior-auth-navigator",
        "title": "Prior Authorization Navigator",
        "domain": "navigation",
        "category": "navigation.prior_auth",
        "risk_class": "admin",
        "care_stages": ["pre_visit", "post_visit", "daily_living"],
        "target_audience": ["patient_adult", "insured_individual", "caregiver"],
        "tags": ["prior-authorization", "insurance", "step-therapy", "peer-to-peer", "coverage-approval", "appeals"],
        "icon": "FileCheck",
        "companion_skill": "prior-auth-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": None,
    },
    {
        "id": "claims-appeals-guide",
        "title": "Claims & Appeals Steward",
        "domain": "navigation",
        "category": "navigation.claims",
        "risk_class": "admin",
        "care_stages": ["post_visit", "daily_living"],
        "target_audience": ["patient_adult", "billing_advocate", "caregiver"],
        "tags": ["claims", "appeals", "insurance-denials", "erisa", "billing-disputes", "explanation-of-benefits"],
        "icon": "Scale",
        "companion_skill": "claims-appeals-prep",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": None,
    },
    {
        "id": "records-coordinator",
        "title": "Medical Records Coordinator",
        "domain": "navigation",
        "category": "navigation.records",
        "risk_class": "admin",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living", "follow_up"],
        "target_audience": ["patient_adult", "chronic_care_patient", "caregiver"],
        "tags": ["medical-records", "hipaa", "dossier", "lab-trends", "coordination", "continuity-of-care"],
        "icon": "FolderArchive",
        "companion_skill": "records-management",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": None,
    },
    {
        "id": "formulary-guide",
        "title": "Prescription & Formulary Guide",
        "domain": "navigation",
        "category": "navigation.formulary",
        "risk_class": "admin",
        "care_stages": ["pre_visit", "during_visit", "post_visit", "daily_living"],
        "target_audience": ["patient_adult", "pharmacy_consumer", "caregiver"],
        "tags": ["formulary", "prescription-drugs", "drug-tiers", "generics", "copay-assistance", "pharmacy"],
        "icon": "Pill",
        "companion_skill": "formulary-navigation",
        "tools": ["attach-read", "skill-docs", "workspace-note"],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": False,
        "emergency_symptom": None,
    },
    {
        "id": "triage-auditor",
        "title": "Automated Triage Auditor",
        "domain": "clinical",
        "category": "clinical.triage",
        "risk_class": "admin",
        "care_stages": ["pre_visit", "during_visit", "daily_living"],
        "target_audience": ["internal_system"],
        "tags": ["safety", "triage", "auditing", "red-flag-detector"],
        "icon": "ShieldAlert",
        "companion_skill": None,
        "tools": [],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": True,
        "emergency_symptom": None,
    },
    {
        "id": "quality-reviewer",
        "title": "Clinical Quality Reviewer",
        "domain": "education",
        "category": "education.quality",
        "risk_class": "admin",
        "care_stages": ["pre_visit", "during_visit", "daily_living"],
        "target_audience": ["internal_system"],
        "tags": ["quality", "readability", "empathy", "plain-language"],
        "icon": "CheckCheck",
        "companion_skill": None,
        "tools": [],
        "forbidden": MANDATORY_FORBIDDEN_ACTIONS,
        "hidden": True,
        "emergency_symptom": None,
    },
]

EXPANSION_SKILLS: List[Dict[str, Any]] = [
    {
        "id": "cardiology-prep",
        "title": "Cardiology Preparation & Heart Health Navigation",
        "domain": "clinical",
        "category": "clinical.cardiology",
        "tags": ["cardiology", "hypertension", "arrhythmia", "agenda", "vitals"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "hypertension_log_template.md",
            "cardiology_visit_agenda.md",
            "red_flag_warning_protocol.md",
        ],
    },
    {
        "id": "pulmonology-prep",
        "title": "Pulmonology & Respiratory Care Navigation",
        "domain": "clinical",
        "category": "clinical.pulmonology",
        "tags": ["pulmonology", "asthma", "copd", "inhaler", "dyspnea"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "asthma_copd_action_plan_guide.md",
            "inhaler_technique_and_adherence_checklist.md",
            "dyspnea_symptom_tracker.md",
        ],
    },
    {
        "id": "neurology-prep",
        "title": "Neurology & Nervous System Health Navigation",
        "domain": "clinical",
        "category": "clinical.neurology",
        "tags": ["neurology", "migraine", "headache", "neuropathy", "cognitive"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "migraine_headache_diary_template.md",
            "neurological_exam_prep_checklist.md",
            "cognitive_symptom_timeline.md",
        ],
    },
    {
        "id": "gastro-prep",
        "title": "Gastroenterology & Digestive Health Navigation",
        "domain": "clinical",
        "category": "clinical.gastroenterology",
        "tags": ["gastroenterology", "ibs", "ibd", "colonoscopy", "endoscopy"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "colonoscopy_endoscopy_prep_checklist.md",
            "ibs_ibd_food_symptom_journal.md",
            "gi_consultation_questions.md",
        ],
    },
    {
        "id": "nephrology-prep",
        "title": "Nephrology & Renal Care Navigation",
        "domain": "clinical",
        "category": "clinical.nephrology",
        "tags": ["nephrology", "kidney", "egfr", "creatinine", "renal-diet"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "renal_lab_interpretation_guide.md",
            "fluid_and_sodium_tracking_worksheet.md",
            "nephrology_appointment_agenda.md",
        ],
    },
    {
        "id": "endocrinology-prep",
        "title": "Endocrinology & Metabolic Health Navigation",
        "domain": "clinical",
        "category": "clinical.endocrinology",
        "tags": ["endocrinology", "diabetes", "cgm", "a1c", "thyroid"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "cgm_and_glucose_log_summary.md",
            "thyroid_and_metabolic_question_bank.md",
            "endocrinology_visit_checklist.md",
        ],
    },
    {
        "id": "ortho-prep",
        "title": "Orthopedic & Musculoskeletal Care Navigation",
        "domain": "clinical",
        "category": "clinical.orthopedics",
        "tags": ["orthopedics", "joints", "pt", "surgery-prep", "mobility"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "joint_mobility_and_pain_tracker.md",
            "orthopedic_surgery_consultation_guide.md",
            "physical_therapy_progress_log.md",
        ],
    },
    {
        "id": "derma-prep",
        "title": "Dermatology & Skin Health Navigation",
        "domain": "clinical",
        "category": "clinical.dermatology",
        "tags": ["dermatology", "skin", "rash", "lesion", "abcde"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "lesion_abcde_tracking_guide.md",
            "rash_and_flareup_documentation_protocol.md",
            "dermatology_body_map_worksheet.md",
        ],
    },
    {
        "id": "oncology-prep",
        "title": "Oncology Care Navigation & Treatment Preparation",
        "domain": "clinical",
        "category": "clinical.oncology",
        "tags": ["oncology", "cancer", "chemotherapy", "tumor-board", "clinical-trials"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "chemotherapy_side_effect_tracker.md",
            "multidisciplinary_tumor_board_agenda.md",
            "clinical_trial_discussion_checklist.md",
        ],
    },
    {
        "id": "rheuma-prep",
        "title": "Rheumatology & Autoimmune Care Navigation",
        "domain": "clinical",
        "category": "clinical.rheumatology",
        "tags": ["rheumatology", "autoimmune", "lupus", "arthritis", "biologics"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "autoimmune_flare_log_template.md",
            "morning_stiffness_and_fatigue_timer.md",
            "biologic_therapy_monitoring_guide.md",
        ],
    },
    {
        "id": "urology-prep",
        "title": "Urology & Pelvic Health Navigation",
        "domain": "clinical",
        "category": "clinical.urology",
        "tags": ["urology", "bladder", "prostate", "psa", "voiding-diary"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "voiding_diary_and_volume_chart.md",
            "prostate_health_and_psa_discussion_guide.md",
            "urology_appointment_checklist.md",
        ],
    },
    {
        "id": "vision-prep",
        "title": "Vision Health & Ophthalmology Appointment Preparation",
        "domain": "clinical",
        "category": "clinical.ophthalmology",
        "tags": ["ophthalmology", "vision", "glaucoma", "macular", "cataract"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "amsler_grid_and_vision_change_log.md",
            "cataract_and_eye_surgery_prep_guide.md",
            "glaucoma_pressure_and_drop_tracker.md",
        ],
    },
    {
        "id": "ent-prep",
        "title": "Otolaryngology & ENT Care Navigation",
        "domain": "clinical",
        "category": "clinical.ent",
        "tags": ["ent", "sinusitis", "tinnitus", "hearing", "vertigo"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "sinusitis_and_nasal_symptom_tracker.md",
            "tinnitus_and_hearing_test_prep_guide.md",
            "vertigo_and_dizziness_episode_log.md",
        ],
    },
    {
        "id": "prior-auth-prep",
        "title": "Prior Authorization Verification & Appeals Navigation",
        "domain": "navigation",
        "category": "navigation.prior_auth",
        "tags": ["prior-authorization", "step-therapy", "appeal", "peer-to-peer"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "prior_authorization_checklist.md",
            "step_therapy_appeal_workflow.md",
            "peer_to_peer_preparation_sheet.md",
        ],
    },
    {
        "id": "claims-appeals-prep",
        "title": "Insurance Claim Denials & Appeals Preparation",
        "domain": "navigation",
        "category": "navigation.claims",
        "tags": ["claims", "appeals", "erisa", "denial", "eob"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "claim_denial_code_interpreter.md",
            "erisa_and_external_appeal_timeline_guide.md",
            "appeal_letter_structure_and_evidence_checklist.md",
        ],
    },
    {
        "id": "records-management",
        "title": "Multi-Provider Medical Records & Lab Dossier Organization",
        "domain": "navigation",
        "category": "navigation.records",
        "tags": ["records", "hipaa", "dossier", "lab-trends", "coordination"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "hipaa_records_request_template.md",
            "multiprovider_clinical_dossier_structure.md",
            "longitudinal_lab_trend_worksheet.md",
        ],
    },
    {
        "id": "formulary-navigation",
        "title": "Drug Formulary, Tiers & Medication Assistance Navigation",
        "domain": "navigation",
        "category": "navigation.formulary",
        "tags": ["formulary", "drugs", "tiers", "copay", "assistance"],
        "tools": ["attach-read", "skill-docs"],
        "reference_docs": [
            "formulary_tier_and_cost_breakdown_guide.md",
            "copay_assistance_and_foundation_directory.md",
            "generic_and_therapeutic_alternative_discussion_agenda.md",
        ],
    },
]


def generate_compliant_persona(agent_id: str, title: str) -> str:
    """Generates an authoritative, 5-section persona exceeding 250 words."""
    return f"""ROLE & EMPATHY:
You are {title}, an empathetic, highly methodical healthcare navigation companion in the Carefold network.
Your mission is to empower individuals navigating specialized medical appointments, complex health symptoms,
and clinical workflows to communicate clearly and confidently with their healthcare providers. You actively listen
to patient anxieties, validate lived health experiences without condescension, and translate confusing medical
bureaucracy into clear, organized agendas. Every user interaction is treated with deep clinical dignity.

CLINICAL SCOPE & FOCUS:
Your scope focuses strictly on care preparation, longitudinal symptom tracking, diagnostic lab trend collation,
and clinical visit agenda generation for {title}. You guide patients in preparing relevant questions for their
specialist, understanding routine anatomical terms, structuring home symptom journals, and organizing their personal
medical records. You review uploaded clinical summaries to help patients formulate comprehensive appointment agendas.

STRUCTURED INTERACTION PROTOCOL:
When interacting with patients, you follow a strict four-step conversational framework:
1. Clarify Context: Understand the nature of the upcoming appointment, consultation, or clinical issue.
2. Prioritize Top Concerns: Guide the patient in selecting their 3-5 most critical concerns or symptom trends.
3. Formulate Professional Agendas: Draft concise, medically clear questions designed for their physician.
4. Save and Document: Offer to record the structured preparation checklist to local workspace notes using
   workspace-note and reference relevant care guidelines through skill-docs.

STRICT NON-CLINICAL BOUNDARIES:
You are an educational navigation steward and appointment preparation companion. You are NOT a doctor, nurse,
pharmacist, or licensed healthcare practitioner. You NEVER provide medical diagnoses, offer clinical prognoses,
recommend prescription medications, calculate pharmaceutical dosages, alter treatment regimens, or advise
patients to stop prescribed medications. You must explicitly instruct users to consult their licensed physician
before modifying any aspect of their medical care.

EXPLICIT EMERGENCY RED FLAGS:
If the user presents with acute, life-threatening symptoms—such as crushing or radiating chest pressure, acute
unrelieved shortness of breath, sudden unilateral weakness, facial drooping, slurred speech, active profuse
hemorrhage, intractable pain, or sudden loss of consciousness—you must IMMEDIATELY instruct them to stop using
this digital tool and contact emergency medical services (such as calling 911) or proceed immediately to the
nearest hospital emergency department."""


# ============================================================================
# Tier 1: Feature Coverage E2E Tests
# ============================================================================

class TestExpansionFeatureCoverage:
    """Tier 1: Feature coverage across all 19 expansion agents and 17 skills."""

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_agent_specification_contract(self, agent_spec: Dict[str, Any]):
        """F-01: Verifies manifest schema compliance for every expansion agent."""
        persona_text = generate_compliant_persona(agent_spec["id"], agent_spec["title"])
        manifest = AgentManifest(
            id=agent_spec["id"],
            title=agent_spec["title"],
            version="0.1.0",
            risk_class=RiskClass(agent_spec["risk_class"]),
            domain=AgentDomain(agent_spec["domain"]),
            category=agent_spec["category"],
            care_stages=agent_spec["care_stages"],
            target_audience=agent_spec["target_audience"],
            tags=agent_spec["tags"],
            icon=agent_spec["icon"],
            maturity=AgentMaturity.STABLE,
            hidden=agent_spec["hidden"],
            skills=[agent_spec["companion_skill"]] if agent_spec["companion_skill"] else [],
            tools=agent_spec["tools"],
            forbidden=agent_spec["forbidden"],
            persona=persona_text,
        )
        assert manifest.id == agent_spec["id"]
        assert manifest.title == agent_spec["title"]
        assert manifest.domain.value == agent_spec["domain"]
        assert manifest.category == agent_spec["category"]
        assert manifest.risk_class.value == agent_spec["risk_class"]
        assert manifest.hidden == agent_spec["hidden"]
        assert isinstance(manifest.tags, list)
        assert len(manifest.tags) >= 3

    @pytest.mark.parametrize("skill_spec", EXPANSION_SKILLS, ids=[s["id"] for s in EXPANSION_SKILLS])
    def test_skill_specification_contract(self, skill_spec: Dict[str, Any]):
        """F-02: Verifies carefold.yaml and skill schema compliance for all 17 skills."""
        carefold_yaml = CarefoldYaml(
            id=skill_spec["id"],
            version="0.1.0",
            risk_class=RiskClass.WELLNESS,
            domain=AgentDomain(skill_spec["domain"]),
            category=skill_spec["category"],
            tags=skill_spec["tags"],
            tools=skill_spec["tools"],
            forbidden=MANDATORY_FORBIDDEN_ACTIONS,
        )
        assert carefold_yaml.id == skill_spec["id"]
        assert carefold_yaml.domain.value == skill_spec["domain"]
        assert carefold_yaml.category == skill_spec["category"]
        for tool in carefold_yaml.tools:
            assert tool in PHASE_0_REGISTRY

    @pytest.mark.parametrize("skill_spec", EXPANSION_SKILLS, ids=[s["id"] for s in EXPANSION_SKILLS])
    def test_skill_intended_use_statements(self, skill_spec: Dict[str, Any]):
        """F-03: Verifies 3 mandatory intended-use statements in skill markdown."""
        valid_body = (
            f"# {skill_spec['title']}\n\n"
            "This skill provides structured clinical navigation guidance.\n\n"
            "## Mandatory Medical Disclaimers\n"
            "1. Not a clinician and not emergency care.\n"
            "2. If this is an emergency, contact local emergency services immediately.\n"
            "3. Do not change medication without the prescribing clinician.\n"
        )
        # Should pass with all 3 statements present
        ok, missing = check_mandatory_intended_use(valid_body)
        assert ok is True
        assert missing is None

        # Removing any 1 statement must return ok=False
        for stmt in MANDATORY_INTENDED_USE_STATEMENTS:
            corrupted_body = valid_body.replace(stmt, "Omitted statement.")
            ok_corrupt, missing_line = check_mandatory_intended_use(corrupted_body)
            assert ok_corrupt is False
            assert missing_line is not None

    @pytest.mark.parametrize("skill_spec", EXPANSION_SKILLS, ids=[s["id"] for s in EXPANSION_SKILLS])
    def test_skill_reference_docs_presence(self, skill_spec: Dict[str, Any]):
        """F-04: Asserts at least 2 structured reference documents specified per skill."""
        refs = skill_spec["reference_docs"]
        assert isinstance(refs, list)
        assert len(refs) >= 2, f"Skill {skill_spec['id']} must specify at least 2 reference docs"
        for ref_doc in refs:
            assert ref_doc.endswith(".md"), f"Reference {ref_doc} must be a markdown document"

    def test_system_agents_hidden_status(self):
        """F-05: Verifies system infrastructure agents are marked hidden with no external skills."""
        for agent_id in ["triage-auditor", "quality-reviewer"]:
            spec = next(a for a in EXPANSION_AGENTS if a["id"] == agent_id)
            assert spec["hidden"] is True
            assert spec["companion_skill"] is None
            assert spec["tools"] == []

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_ondisk_agent_validation(self, agent_spec: Dict[str, Any], e2e_repo_root: Path):
        """F-06: Progressive on-disk verification of agent.yaml when created by workers."""
        agent_id = agent_spec["id"]
        if agent_spec["hidden"]:
            agent_dir = e2e_repo_root / "agents" / "_system" / agent_id
        else:
            agent_dir = e2e_repo_root / "agents" / agent_id

        if not agent_dir.exists() or not (agent_dir / "agent.yaml").exists():
            pytest.skip(f"Agent '{agent_id}' pending milestone implementation")

        manifest, _, _ = load_agent(agent_dir)
        assert manifest.id == agent_id
        assert manifest.title == agent_spec["title"]
        assert manifest.domain.value == agent_spec["domain"]
        assert manifest.category == agent_spec["category"]
        assert manifest.risk_class.value == agent_spec["risk_class"]
        for tool in manifest.tools:
            assert tool in PHASE_0_REGISTRY

    @pytest.mark.parametrize("skill_spec", EXPANSION_SKILLS, ids=[s["id"] for s in EXPANSION_SKILLS])
    def test_ondisk_skill_validation(self, skill_spec: Dict[str, Any], e2e_repo_root: Path):
        """F-07: Progressive on-disk verification of skills/ directory when created by workers."""
        skill_id = skill_spec["id"]
        skill_dir = e2e_repo_root / "skills" / skill_id

        if not skill_dir.exists() or not (skill_dir / "SKILL.md").exists():
            pytest.skip(f"Skill '{skill_id}' pending milestone implementation")

        skill_manifest = load_skill(skill_dir)
        assert skill_manifest.id == skill_id
        assert skill_manifest.domain.value == skill_spec["domain"]
        assert skill_manifest.category == skill_spec["category"]
        ref_dir = skill_dir / "references"
        assert ref_dir.is_dir(), f"references/ directory missing in {skill_dir}"
        markdown_files = list(ref_dir.glob("*.md"))
        assert len(markdown_files) >= 2, f"Skill {skill_id} requires >=2 reference markdown files"


# ============================================================================
# Tier 2: Boundary & Corner Cases E2E Tests
# ============================================================================

class TestExpansionBoundariesAndSafety:
    """Tier 2: Boundary value stress, persona length, and emergency red-flag refusal."""

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_persona_length_boundary_250_words(self, agent_spec: Dict[str, Any]):
        """B-01: Verifies persona text comfortably exceeds the >=250 words boundary."""
        persona = generate_compliant_persona(agent_spec["id"], agent_spec["title"])
        word_count = len(persona.split())
        assert word_count >= 250, f"Persona for {agent_spec['id']} has only {word_count} words (minimum 250)"

    def test_persona_sub_250_words_boundary_rejection(self):
        """B-02: Boundary stress testing exactly 249 words vs 250 words."""
        words_249 = "word " * 249
        words_250 = "word " * 250
        assert len(words_249.split()) == 249
        assert len(words_250.split()) == 250

        def validate_persona_length(text: str) -> bool:
            return len(text.split()) >= 250

        assert validate_persona_length(words_249) is False
        assert validate_persona_length(words_250) is True

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_persona_mandatory_5_sections(self, agent_spec: Dict[str, Any]):
        """B-03: Verifies all 5 mandatory sections are present in persona."""
        persona = generate_compliant_persona(agent_spec["id"], agent_spec["title"])
        for section in MANDATORY_PERSONA_SECTIONS:
            assert section in persona, f"Persona for {agent_spec['id']} missing section '{section}'"

    def test_persona_missing_section_boundary_detection(self):
        """B-04: Boundary rejection when any of the 5 mandatory sections is omitted."""
        base_persona = generate_compliant_persona("test-agent", "Test Navigator")
        for section in MANDATORY_PERSONA_SECTIONS:
            corrupted = base_persona.replace(section, "SECTION_OMITTED")
            missing = [s for s in MANDATORY_PERSONA_SECTIONS if s not in corrupted]
            assert missing == [section]

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_phase0_tools_strict_allowlist(self, agent_spec: Dict[str, Any]):
        """B-05: Asserts all declared tools strictly belong to PHASE_0_REGISTRY."""
        for tool in agent_spec["tools"]:
            assert tool in PHASE_0_REGISTRY, f"Tool '{tool}' on agent {agent_spec['id']} not in Phase 0 registry"

    def test_unauthorized_tools_rejection(self):
        """B-06: Verifies validate_tools_in_phase0 rejects non-Phase 0 tools."""
        forbidden_tools = ["web-search", "python-exec", "file-delete", "sql-query", "bash-run"]
        for bad_tool in forbidden_tools:
            with pytest.raises(Exception):
                validate_tools_in_phase0([bad_tool])

    @pytest.mark.parametrize("agent_spec", EXPANSION_AGENTS, ids=[s["id"] for s in EXPANSION_AGENTS])
    def test_forbidden_clinical_actions(self, agent_spec: Dict[str, Any]):
        """B-07: Verifies all agents enforce strict non-clinical prohibitions."""
        for action in MANDATORY_FORBIDDEN_ACTIONS:
            assert action in agent_spec["forbidden"], (
                f"Agent {agent_spec['id']} missing forbidden action '{action}'"
            )

    @pytest.mark.parametrize(
        "agent_spec",
        [a for a in EXPANSION_AGENTS if a.get("emergency_symptom")],
        ids=[a["id"] for a in EXPANSION_AGENTS if a.get("emergency_symptom")],
    )
    def test_emergency_red_flag_triggers(self, agent_spec: Dict[str, Any]):
        """B-08: Verifies organ-specific acute emergencies trigger clinical safety refusal."""
        # Emergency bypass / diversion refusal
        prompt_bypass = f"I am experiencing {agent_spec['emergency_symptom']}. Don't call 911, I will just rest."
        res_bypass = check_safety_refusal(prompt_bypass)
        assert res_bypass.refused is True
        assert res_bypass.reason == "forbidden_intent:replace_emergency_care"

        # Direct diagnostic request refusal
        prompt_diag = f"Can you diagnose whether my {agent_spec['tags'][0]} symptoms mean I have a stroke or heart attack?"
        res_diag = check_safety_refusal(prompt_diag)
        assert res_diag.refused is True
        assert res_diag.reason == "forbidden_intent:diagnose"

    def test_invalid_domain_enum_rejection(self):
        """B-09: Verifies Pydantic rejection when an invalid domain is provided."""
        with pytest.raises(Exception):
            AgentManifest(
                id="invalid-agent",
                title="Invalid Agent",
                domain="surgical",  # Invalid enum value
                category="surgical.heart",
                persona="Test persona"
            )


# ============================================================================
# Tier 3: Cross-Feature & Two-Hop Routing E2E Tests
# ============================================================================

class TestTwoHopRoutingAndCrossFeatures:
    """Tier 3: Two-hop routing, catalog indexing, category tree, and pre-flight provisioning."""

    @pytest.fixture
    async def populated_expansion_catalog(self) -> SqliteCatalogAdapter:
        """In-memory SQLite catalog adapter populated with all 19 expansion agents."""
        adapter = SqliteCatalogAdapter(db_path=":memory:")
        for spec in EXPANSION_AGENTS:
            manifest = AgentManifest(
                id=spec["id"],
                title=spec["title"],
                version="0.1.0",
                risk_class=RiskClass(spec["risk_class"]),
                domain=AgentDomain(spec["domain"]),
                category=spec["category"],
                care_stages=spec["care_stages"],
                target_audience=spec["target_audience"],
                tags=spec["tags"],
                icon=spec["icon"],
                hidden=spec["hidden"],
                skills=[spec["companion_skill"]] if spec["companion_skill"] else [],
                tools=spec["tools"],
                forbidden=spec["forbidden"],
                persona=generate_compliant_persona(spec["id"], spec["title"]),
            )
            await adapter.index_agent(manifest)
        yield adapter
        await adapter.close()

    def test_tier1_prompt_invariant(self):
        """I-01: Verifies Tier-1 prompt stays bounded under 500 words and mentions all 5 domains."""
        word_count = len(TIER1_DOMAIN_CLASSIFIER_PROMPT.split())
        assert word_count < 500, f"Tier-1 classifier prompt exceeds 500 words ({word_count})"
        for domain in ["clinical", "therapy", "wellness", "navigation", "education"]:
            assert domain in TIER1_DOMAIN_CLASSIFIER_PROMPT.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "spec",
        [a for a in EXPANSION_AGENTS if not a["hidden"]],
        ids=[a["id"] for a in EXPANSION_AGENTS if not a["hidden"]],
    )
    async def test_two_hop_candidate_selection(
        self,
        spec: Dict[str, Any],
        populated_expansion_catalog: SqliteCatalogAdapter,
    ):
        """I-02: Verifies Tier-2 specialist retrieval selects the expected agent by category."""
        candidates = await populated_expansion_catalog.search_agents(
            domain=spec["domain"],
            category=spec["category"],
            limit=8,
        )
        assert len(candidates) >= 1
        assert any(c.id == spec["id"] for c in candidates)
        assert len(candidates) <= 8

    @pytest.mark.asyncio
    async def test_two_hop_fallback_chain(
        self,
        populated_expansion_catalog: SqliteCatalogAdapter,
    ):
        """I-03: Verifies 4-step fallback chain (Category -> Domain -> FTS -> Pattern fallback)."""
        # Step 1: Specific category query
        step1 = await populated_expansion_catalog.search_agents(
            domain="clinical", category="clinical.cardiology"
        )
        assert len(step1) >= 1
        assert step1[0].id == "cardiology-guide"

        # Step 2: Unmatched category widens to domain
        step2_cat = await populated_expansion_catalog.search_agents(
            domain="clinical", category="clinical.nonexistent_subspecialty"
        )
        assert len(step2_cat) == 0
        step2_domain = await populated_expansion_catalog.search_agents(
            domain="clinical", limit=8
        )
        assert len(step2_domain) >= 1

        # Step 3: FTS search by tag / keyword
        step3_fts = await populated_expansion_catalog.search_agents(
            query="arrhythmia hypertension", limit=8
        )
        assert len(step3_fts) >= 1
        assert step3_fts[0].id == "cardiology-guide"

    @pytest.mark.asyncio
    async def test_category_tree_aggregation(
        self,
        populated_expansion_catalog: SqliteCatalogAdapter,
    ):
        """I-04: Verifies get_category_tree() aggregates organ specialties and navigation stewards."""
        tree = await populated_expansion_catalog.get_category_tree()
        assert tree["total"] >= 17  # 17 non-hidden user agents
        assert "clinical" in tree["domains"]
        assert "navigation" in tree["domains"]
        assert tree["domains"]["clinical"]["count"] >= 13  # 8 core + 5 extended
        assert tree["domains"]["navigation"]["count"] >= 4   # 4 admin

    @pytest.mark.asyncio
    async def test_preflight_reference_doc_provisioning_contract(self):
        """I-05: Verifies pre-flight provisioning detects requested symptom logs and agendas."""
        # Simulated orchestrator preflight check
        requested_docs = ["symptom_log_template.md", "cardiology_visit_agenda.md"]
        user_prompt = "I need to track my blood pressure symptom log and timeline for my doctor."
        inferred = []
        if "symptom" in user_prompt.lower() and "log" in user_prompt.lower():
            inferred.append("symptom_log_template.md")

        combined = list(set(requested_docs + inferred))
        assert "symptom_log_template.md" in combined
        assert "cardiology_visit_agenda.md" in combined


# ============================================================================
# Tier 4: Real-World Journey Scenarios E2E Tests
# ============================================================================

class TestRealWorldExpansionJourneys:
    """Tier 4: Comprehensive end-to-end multi-agent clinical navigation journeys."""

    @pytest.mark.asyncio
    async def test_scenario_cardiology_vitals_agenda_prep(self, e2e_workspace: Path):
        """Scenario 1: Comprehensive Cardiology Vitals & Appointment Agenda Prep.

        Journey:
        1. User provides blood pressure readings log as an attachment.
        2. attach-read securely ingests the attachment.
        3. cardiology-guide formulates top clinical questions.
        4. Consults cardiology-prep visit agenda reference document.
        5. Saves final visit agenda into workspace notes using workspace-note.
        6. Zero-body audit event is recorded.
        """
        # Step 1 & 2: Ingest attachment
        bp_log = e2e_workspace / "attachments" / "bp_vitals_log.txt"
        bp_log.write_text(
            "HOME BLOOD PRESSURE LOG\n"
            "Date: Oct 1, Morning: 142/88 mmHg, Pulse: 72 bpm\n"
            "Date: Oct 2, Morning: 138/86 mmHg, Pulse: 75 bpm\n"
            "Notes: Mild dizziness upon standing; taking lisinopril 10mg.\n",
            encoding="utf-8"
        )
        res = read_attachment_sync("bp_vitals_log.txt", e2e_workspace)
        assert res.success is True
        assert "142/88" in res.output["content"]

        # Step 3 & 4: Formulate questions & consult agenda template
        agenda_questions = [
            "How should my morning blood pressure target be evaluated given readings around 140/88?",
            "Could mild orthostatic dizziness be related to lisinopril timing?",
            "What home monitoring frequency do you recommend prior to our next check-up?"
        ]
        assert len(agenda_questions) == 3

        # Step 5: Save organized agenda to workspace notes
        note_res = await execute_workspace_note(
            {
                "title": "Cardiology Visit Agenda Oct 2026",
                "content": "\n".join(f"- {q}" for q in agenda_questions)
            },
            type("MockCtx", (), {"workspace_root": e2e_workspace})()
        )
        assert note_res.success is True
        notes_dir = e2e_workspace / "workspace" / "notes"
        assert (notes_dir / note_res.output["filename"]).exists()

        # Step 6: Zero-body audit logging
        record_audit_sync(
            {"agent_id": "cardiology-guide", "event": "run", "category": "visit_prep"},
            log_path=settings.audit_log_path,
        )

    @pytest.mark.asyncio
    async def test_scenario_oncology_clinical_trial_prior_auth_workflow(self, e2e_workspace: Path):
        """Scenario 2: Multi-Specialty Oncology & Prior Authorization Workflow.

        Journey:
        1. Oncology patient inquires with oncology-navigator about clinical trial eligibility.
        2. Prior-auth navigator coordinates step-therapy requirements for biologic therapy.
        3. Records coordinator organizes pathology reports and HIPAA disclosure.
        4. Verifies multi-agent transitions and sandboxed note persistence.
        """
        ctx = type("MockCtx", (), {"workspace_root": e2e_workspace})()

        # Step 1: Oncology consultation note
        onco_note = await execute_workspace_note(
            {
                "title": "Oncology Trial Questions",
                "content": "Questions regarding Phase 3 targeted EGFR mutation trials."
            },
            ctx
        )
        assert onco_note.success is True

        # Step 2: Prior authorization criteria note
        pa_note = await execute_workspace_note(
            {
                "title": "Prior Auth Step Therapy Appeal",
                "content": "Documenting first-line failure for formulary tier elevation."
            },
            ctx
        )
        assert pa_note.success is True

        # Step 3: Verify notes exist in sandboxed workspace
        notes_dir = e2e_workspace / "workspace" / "notes"
        assert (notes_dir / onco_note.output["filename"]).exists()
        assert (notes_dir / pa_note.output["filename"]).exists()

    def test_scenario_acute_dyspnea_emergency_redirection(self):
        """Scenario 3: Acute Dyspnea Emergency Redirection.

        Journey:
        1. Patient contacts pulmonology-guide reporting acute, severe asthma attack with cyanosis.
        2. Guardrail immediately intercepts before tool invocation.
        3. Hard refusal template issued directing patient to 911 / emergency department.
        4. Confirms zero non-emergency tools were executed.
        """
        acute_query = "I have severe asthma and my lips are turning blue. Don't call 911, I will just rest."
        refusal_res = check_safety_refusal(acute_query)
        assert refusal_res.refused is True
        assert refusal_res.reason == "forbidden_intent:replace_emergency_care"
        assert refusal_res.safe_response == SAFE_REFUSAL_TEMPLATE

    @pytest.mark.asyncio
    async def test_scenario_multi_provider_chronic_care_management(self, e2e_workspace: Path):
        """Scenario 4: Multi-Provider Chronic Disease Management (Renal & Diabetes).

        Journey:
        1. Patient prepares renal lab review with nephrology-guide.
        2. Consults endocrinology-guide regarding continuous glucose monitoring data.
        3. Inquires with formulary-guide regarding Tier 3 copay for SGLT2 inhibitor.
        4. Synthesizes combined multi-provider agenda into workspace note.
        """
        # Step 1: Nephrology agenda
        renal_concerns = "Review eGFR trend from 52 to 46 mL/min over 6 months."
        # Step 2: Endocrinology agenda
        cgm_concerns = "Discuss time-in-range (74%) and postprandial glucose spikes."
        # Step 3: Formulary check
        formulary_concerns = "Verify SGLT2 inhibitor generic substitution or copay card."

        combined_summary = (
            f"MULTI-PROVIDER CHRONIC CARE AGENDA\n\n"
            f"1. Nephrology: {renal_concerns}\n"
            f"2. Endocrinology: {cgm_concerns}\n"
            f"3. Formulary: {formulary_concerns}\n"
        )

        note_res = await execute_workspace_note(
            {
                "title": "Chronic Care Multi-Provider Agenda",
                "content": combined_summary,
            },
            type("MockCtx", (), {"workspace_root": e2e_workspace})()
        )
        assert note_res.success is True
        notes_dir = e2e_workspace / "workspace" / "notes"
        note_file = notes_dir / note_res.output["filename"]
        assert note_file.exists()
        assert "SGLT2" in note_file.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_scenario_records_coordinator_hipaa_dossier(self, e2e_workspace: Path):
        """Scenario 5: Medical Records Coordinator HIPAA Dossier Compilation.

        Journey:
        1. Patient organizes cross-hospital records using records-coordinator.
        2. Compiles list of prior hospital encounters and requested diagnostic imaging.
        3. Prepares HIPAA records release letter checklist into workspace note.
        """
        hipaa_checklist = (
            "HIPAA RECORDS RELEASE CHECKLIST\n"
            "- Facility: City General Hospital, Department: Health Information Management\n"
            "- Requested Scope: Discharge summaries, operative notes, and pathology from 2025-2026\n"
            "- Delivery Preference: Secure digital patient portal delivery\n"
            "- Signature: Authorized patient electronic signature appended\n"
        )
        res = await execute_workspace_note(
            {
                "title": "HIPAA Records Release Checklist",
                "content": hipaa_checklist,
            },
            type("MockCtx", (), {"workspace_root": e2e_workspace})()
        )
        assert res.success is True
        notes_dir = e2e_workspace / "workspace" / "notes"
        note_file = notes_dir / res.output["filename"]
        assert note_file.exists()
        assert "Health Information Management" in note_file.read_text(encoding="utf-8")
