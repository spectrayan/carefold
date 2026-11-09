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

"""Comprehensive unit and security tests for the FHIR R4 declarative registry and Bundle parser (#281)."""

from __future__ import annotations

import json
from typing import Any, Dict, List
import uuid

import pytest

from carefold.fhir import (
    CARE_PLAN_AND_ADMIN_RESOURCE_TYPES,
    CLINICAL_CORE_RESOURCE_TYPES,
    CLINICAL_FHIR_RESOURCE_TYPES,
    DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES,
    DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES,
    FHIR_VALIDATION_CAPABILITIES,
    PAPERWORK_FHIR_RESOURCE_TYPES,
    R4B_ONLY_RESOURCE_TYPES,
    SUPPORTED_FHIR_RESOURCE_TYPES,
    TARGET_FHIR_RELEASE,
    TARGET_FHIR_VERSION,
    classify_fhir_reference,
    evaluate_fhirpath,
    extract_codings,
    extract_effective_iso,
    extract_references,
    get_r4_model_class,
    resolve_resource_scope,
    validate_and_normalize_fhir_resource,
)
from carefold.importers.fhir_bundle import parse_fhir_bundle

# Representative valid FHIR R4 payloads across all 33 allowlisted resource types
REPRESENTATIVE_R4_RESOURCES: Dict[str, Dict[str, Any]] = {
    # Demographics & Care Team (7)
    "Patient": {
        "resourceType": "Patient",
        "id": "pat-maya-1",
        "identifier": [{"system": "http://hospital.example.org/mrn", "value": "MRN-1001"}],
        "name": [{"family": "Patel", "given": ["Maya"]}],
        "gender": "female",
        "birthDate": "1988-11-23",
    },
    "RelatedPerson": {
        "resourceType": "RelatedPerson",
        "id": "rel-spouse-1",
        "patient": {"reference": "Patient/pat-maya-1"},
        "relationship": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "SPS",
                        "display": "spouse",
                    }
                ]
            }
        ],
        "name": [{"family": "Patel", "given": ["Arjun"]}],
    },
    "Practitioner": {
        "resourceType": "Practitioner",
        "id": "prac-cardio-1",
        "name": [{"family": "Chen", "given": ["Elena"], "prefix": ["Dr."]}],
        "qualification": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0360",
                            "code": "MD",
                            "display": "Doctor of Medicine",
                        }
                    ]
                }
            }
        ],
    },
    "PractitionerRole": {
        "resourceType": "PractitionerRole",
        "id": "prac-role-1",
        "practitioner": {"reference": "Practitioner/prac-cardio-1"},
        "organization": {"reference": "Organization/org-heart-1"},
        "code": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "17561000",
                        "display": "Cardiologist",
                    }
                ]
            }
        ],
        "specialty": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "394579002",
                        "display": "Cardiology",
                    }
                ]
            }
        ],
    },
    "Organization": {
        "resourceType": "Organization",
        "id": "org-heart-1",
        "name": "City General Heart Institute",
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/organization-type",
                        "code": "prov",
                        "display": "Healthcare Provider",
                    }
                ]
            }
        ],
    },
    "CareTeam": {
        "resourceType": "CareTeam",
        "id": "careteam-1",
        "status": "active",
        "name": "Cardiometabolic Care Team",
        "subject": {"reference": "Patient/pat-maya-1"},
        "participant": [
            {
                "role": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "17561000",
                                "display": "Cardiologist",
                            }
                        ]
                    }
                ],
                "member": {"reference": "Practitioner/prac-cardio-1"},
            }
        ],
    },
    "Location": {
        "resourceType": "Location",
        "id": "loc-clinic-1",
        "status": "active",
        "name": "West Wing Outpatient Cardiology",
        "managingOrganization": {"reference": "Organization/org-heart-1"},
        "type": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                        "code": "CARD",
                        "display": "Ambulatory Health Care Facilities; Clinic/Center; Rehabilitation: Cardiac Facilities",
                    }
                ]
            }
        ],
    },
    # Clinical Core (10)
    "Condition": {
        "resourceType": "Condition",
        "id": "cond-htn-1",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": "I10",
                    "display": "Essential (primary) hypertension",
                },
                {
                    "system": "http://snomed.info/sct",
                    "code": "59621000",
                    "display": "Essential hypertension",
                },
            ],
            "text": "Essential hypertension",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "recordedDate": "2026-02-14",
    },
    "AllergyIntolerance": {
        "resourceType": "AllergyIntolerance",
        "id": "allergy-pen-1",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active",
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "7980",
                    "display": "Penicillin G",
                }
            ],
            "text": "Penicillin G",
        },
        "patient": {"reference": "Patient/pat-maya-1"},
        "recordedDate": "2025-11-01",
    },
    "MedicationRequest": {
        "resourceType": "MedicationRequest",
        "id": "medreq-lisinopril-1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "314076",
                    "display": "Lisinopril 10 MG Oral Tablet",
                }
            ],
            "text": "Lisinopril 10 MG Oral Tablet",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "requester": {"reference": "Practitioner/prac-cardio-1"},
        "reasonReference": [{"reference": "Condition/cond-htn-1"}],
        "authoredOn": "2026-02-14T10:30:00Z",
    },
    "MedicationStatement": {
        "resourceType": "MedicationStatement",
        "id": "medstmt-lisinopril-1",
        "status": "active",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "314076",
                    "display": "Lisinopril 10 MG Oral Tablet",
                }
            ],
            "text": "Lisinopril 10 MG Oral Tablet",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "effectiveDateTime": "2026-02-15",
    },
    "MedicationDispense": {
        "resourceType": "MedicationDispense",
        "id": "meddisp-lisinopril-1",
        "status": "completed",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "314076",
                    "display": "Lisinopril 10 MG Oral Tablet",
                }
            ]
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "authorizingPrescription": [{"reference": "MedicationRequest/medreq-lisinopril-1"}],
        "whenHandedOver": "2026-02-14T14:00:00Z",
    },
    "Medication": {
        "resourceType": "Medication",
        "id": "med-atorvastatin-1",
        "code": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "617312",
                    "display": "Atorvastatin 10 MG Oral Tablet",
                }
            ],
            "text": "Atorvastatin 10 MG Oral Tablet",
        },
    },
    "Immunization": {
        "resourceType": "Immunization",
        "id": "imm-flu-1",
        "status": "completed",
        "vaccineCode": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/cvx",
                    "code": "141",
                    "display": "Influenza, seasonal, injectable",
                }
            ],
            "text": "Influenza, seasonal, injectable",
        },
        "patient": {"reference": "Patient/pat-maya-1"},
        "occurrenceDateTime": "2025-10-15",
    },
    "Procedure": {
        "resourceType": "Procedure",
        "id": "proc-echo-1",
        "status": "completed",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "40701008",
                    "display": "Echocardiography",
                }
            ],
            "text": "Transthoracic Echocardiography",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "performedDateTime": "2026-02-14T11:00:00Z",
    },
    "FamilyMemberHistory": {
        "resourceType": "FamilyMemberHistory",
        "id": "fmh-father-1",
        "status": "completed",
        "patient": {"reference": "Patient/pat-maya-1"},
        "relationship": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                    "code": "FTH",
                    "display": "father",
                }
            ]
        },
        "date": "2026-02-14",
        "condition": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "53741008",
                            "display": "Coronary arteriosclerosis",
                        }
                    ]
                }
            }
        ],
    },
    "Device": {
        "resourceType": "Device",
        "id": "dev-bp-cuff-1",
        "status": "active",
        "deviceName": [{"name": "Omron Evolv Upper Arm BP Monitor", "type": "user-friendly-name"}],
        "type": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "43770009",
                    "display": "Doppler blood pressure monitor",
                }
            ]
        },
        "patient": {"reference": "Patient/pat-maya-1"},
    },
    # Diagnostics, Labs, Vitals, Imaging & Documents (6)
    "Observation": {
        "resourceType": "Observation",
        "id": "obs-bp-panel-1",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "vital-signs",
                        "display": "Vital Signs",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "85354-9",
                    "display": "Blood pressure panel with all children optional",
                }
            ],
            "text": "Blood pressure panel",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "performer": [{"reference": "Practitioner/prac-cardio-1"}],
        "device": {"reference": "Device/dev-bp-cuff-1"},
        "effectiveDateTime": "2026-02-14T10:15:00Z",
        "component": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8480-6",
                            "display": "Systolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {"value": 128, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
            {
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "8462-4",
                            "display": "Diastolic blood pressure",
                        }
                    ]
                },
                "valueQuantity": {"value": 82, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"},
            },
        ],
    },
    "DiagnosticReport": {
        "resourceType": "DiagnosticReport",
        "id": "diag-lipid-1",
        "status": "final",
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "24331-1",
                    "display": "Lipid 1996 panel - Serum or Plasma",
                }
            ],
            "text": "Lipid Panel",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "effectiveDateTime": "2026-02-14T12:00:00Z",
        "specimen": [{"reference": "Specimen/spec-blood-1"}],
        "result": [{"reference": "Observation/obs-bp-panel-1"}],
    },
    "ImagingStudy": {
        "resourceType": "ImagingStudy",
        "id": "img-echo-1",
        "status": "available",
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "started": "2026-02-14T11:05:00Z",
        "modality": [
            {
                "system": "http://dicom.nema.org/resources/ontology/DCM",
                "code": "US",
                "display": "Ultrasound",
            }
        ],
    },
    "Specimen": {
        "resourceType": "Specimen",
        "id": "spec-blood-1",
        "status": "available",
        "type": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "119297000",
                    "display": "Blood specimen",
                }
            ]
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "receivedTime": "2026-02-14T10:45:00Z",
    },
    "DocumentReference": {
        "resourceType": "DocumentReference",
        "id": "docref-visit-note-1",
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "34117-2",
                    "display": "History and physical note",
                }
            ],
            "text": "Cardiology Consultation Note",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "author": [{"reference": "Practitioner/prac-cardio-1"}],
        "date": "2026-02-14T13:00:00Z",
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "title": "Visit Summary",
                }
            }
        ],
    },
    "Media": {
        "resourceType": "Media",
        "id": "media-ecg-strip-1",
        "status": "completed",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/media-type",
                    "code": "image",
                    "display": "Image",
                }
            ]
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "createdDateTime": "2026-02-14T10:20:00Z",
        "content": {
            "contentType": "image/png",
            "title": "ECG Rhythm Strip",
        },
    },
    # Visits, Care Plans, Goals & Administrative/Payer (10)
    "Encounter": {
        "resourceType": "Encounter",
        "id": "enc-visit-1",
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "type": [
            {
                "coding": [
                    {
                        "system": "http://www.ama-assn.org/go/cpt",
                        "code": "99214",
                        "display": "Office or other outpatient visit",
                    }
                ]
            }
        ],
        "subject": {"reference": "Patient/pat-maya-1"},
        "serviceProvider": {"reference": "Organization/org-heart-1"},
        "location": [{"location": {"reference": "Location/loc-clinic-1"}}],
        "period": {"start": "2026-02-14T10:00:00Z", "end": "2026-02-14T11:30:00Z"},
    },
    "CarePlan": {
        "resourceType": "CarePlan",
        "id": "careplan-htn-1",
        "status": "active",
        "intent": "plan",
        "title": "Hypertension Management Plan",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/us/core/CodeSystem/careplan-category",
                        "code": "assess-plan",
                        "display": "Assessment and Plan of Treatment",
                    }
                ]
            }
        ],
        "subject": {"reference": "Patient/pat-maya-1"},
        "addresses": [{"reference": "Condition/cond-htn-1"}],
        "goal": [{"reference": "Goal/goal-bp-1"}],
        "careTeam": [{"reference": "CareTeam/careteam-1"}],
        "period": {"start": "2026-02-14"},
    },
    "Goal": {
        "resourceType": "Goal",
        "id": "goal-bp-1",
        "lifecycleStatus": "active",
        "description": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "135840009",
                    "display": "Blood pressure monitoring",
                }
            ],
            "text": "Maintain home blood pressure below 130/80 mmHg",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "startDate": "2026-02-14",
    },
    "ServiceRequest": {
        "resourceType": "ServiceRequest",
        "id": "srvreq-echo-1",
        "status": "active",
        "intent": "order",
        "code": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "code": "40701008",
                    "display": "Echocardiography",
                }
            ],
            "text": "Follow-up Echocardiogram",
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "requester": {"reference": "Practitioner/prac-cardio-1"},
        "authoredOn": "2026-02-14T11:20:00Z",
    },
    "QuestionnaireResponse": {
        "resourceType": "QuestionnaireResponse",
        "id": "qr-phq2-1",
        "status": "completed",
        "subject": {"reference": "Patient/pat-maya-1"},
        "authored": "2026-02-14T09:50:00Z",
        "item": [
            {
                "linkId": "q1",
                "text": "Little interest or pleasure in doing things",
                "answer": [
                    {
                        "valueCoding": {
                            "system": "http://loinc.org",
                            "code": "LA6568-5",
                            "display": "Not at all",
                        }
                    }
                ],
            }
        ],
    },
    "Coverage": {
        "resourceType": "Coverage",
        "id": "cov-ppo-1",
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "HIP",
                    "display": "health insurance plan policy",
                }
            ]
        },
        "beneficiary": {"reference": "Patient/pat-maya-1"},
        "payor": [{"reference": "Organization/org-heart-1"}],
        "period": {"start": "2026-01-01", "end": "2026-12-31"},
    },
    "ExplanationOfBenefit": {
        "resourceType": "ExplanationOfBenefit",
        "id": "eob-claim-1",
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                    "code": "professional",
                    "display": "Professional",
                }
            ]
        },
        "use": "claim",
        "patient": {"reference": "Patient/pat-maya-1"},
        "created": "2026-02-16T08:00:00Z",
        "insurer": {"reference": "Organization/org-heart-1"},
        "provider": {"reference": "Practitioner/prac-cardio-1"},
        "outcome": "complete",
        "insurance": [{"focal": True, "coverage": {"reference": "Coverage/cov-ppo-1"}}],
    },
    "Consent": {
        "resourceType": "Consent",
        "id": "consent-hipaa-1",
        "status": "active",
        "scope": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/consentscope",
                    "code": "patient-privacy",
                    "display": "Privacy Consent",
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://loinc.org",
                        "code": "59284-0",
                        "display": "Consent Document",
                    }
                ]
            }
        ],
        "patient": {"reference": "Patient/pat-maya-1"},
        "dateTime": "2026-02-14T09:45:00Z",
    },
    "Provenance": {
        "resourceType": "Provenance",
        "id": "prov-source-1",
        "recorded": "2026-02-14T13:05:00Z",
        "target": [{"reference": "Condition/cond-htn-1"}],
        "activity": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-DataOperation",
                    "code": "CREATE",
                    "display": "create",
                }
            ]
        },
        "agent": [{"who": {"reference": "Practitioner/prac-cardio-1"}}],
    },
    "Composition": {
        "resourceType": "Composition",
        "id": "comp-visit-summary-1",
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "11503-0",
                    "display": "Medical records",
                }
            ]
        },
        "subject": {"reference": "Patient/pat-maya-1"},
        "encounter": {"reference": "Encounter/enc-visit-1"},
        "date": "2026-02-14T13:10:00Z",
        "author": [{"reference": "Practitioner/prac-cardio-1"}],
        "title": "Outpatient Cardiology Summary",
        "section": [
            {
                "title": "Active Problems",
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "11450-4",
                            "display": "Problem list - Reported",
                        }
                    ]
                },
                "entry": [{"reference": "Condition/cond-htn-1"}],
            }
        ],
    },
}


def test_registry_covers_all_33_allowlisted_r4_resource_types():
    """Verifies the allowlist has all 33 expected R4 resource types and documents R4/R4B conformance."""
    assert len(SUPPORTED_FHIR_RESOURCE_TYPES) == 33
    assert set(REPRESENTATIVE_R4_RESOURCES.keys()) == set(SUPPORTED_FHIR_RESOURCE_TYPES)
    assert TARGET_FHIR_RELEASE == "R4"
    assert TARGET_FHIR_VERSION == "4.0.1"
    assert FHIR_VALIDATION_CAPABILITIES["us_core_profile_validation"] is False
    assert FHIR_VALIDATION_CAPABILITIES["ips_profile_validation"] is False
    assert (
        DEMOGRAPHIC_AND_CARE_TEAM_RESOURCE_TYPES
        | CLINICAL_CORE_RESOURCE_TYPES
        | DIAGNOSTIC_AND_VITALS_RESOURCE_TYPES
        | CARE_PLAN_AND_ADMIN_RESOURCE_TYPES
    ) == SUPPORTED_FHIR_RESOURCE_TYPES

    for rtype in SUPPORTED_FHIR_RESOURCE_TYPES:
        cls = get_r4_model_class(rtype)
        assert cls is not None, f"Missing model class for {rtype}"


@pytest.mark.parametrize("rtype", sorted(SUPPORTED_FHIR_RESOURCE_TYPES))
def test_individual_validation_and_extraction_for_all_33_resource_types(rtype: str):
    """Validates and extracts codings, effective dates, and references for each allowlisted R4 type."""
    payload = REPRESENTATIVE_R4_RESOURCES[rtype]
    val_res = validate_and_normalize_fhir_resource(payload, rtype=rtype)
    assert val_res.is_valid is True, f"Validation failed for {rtype}: {val_res.diagnostics}"
    assert val_res.resource_type == rtype
    assert val_res.raw_resource == payload

    expected_scope = "health.paperwork" if rtype in PAPERWORK_FHIR_RESOURCE_TYPES else "health.clinical"
    assert resolve_resource_scope(rtype, val_res.normalized) == expected_scope

    effective_iso, date_part = extract_effective_iso(val_res.normalized, rtype=rtype)
    assert len(date_part) == 10
    assert "T" in effective_iso

    codings = extract_codings(val_res.normalized, rtype=rtype)
    if rtype != "Patient":
        assert len(codings) >= 1, f"Expected at least 1 coding extracted for {rtype}"


def test_parse_comprehensive_33_type_bundle_and_scope_routing():
    """Parses a single Bundle containing all 33 allowlisted R4 resource types and verifies scope routing."""
    profile_id = str(uuid.uuid4())
    bundle = {
        "resourceType": "Bundle",
        "id": "bundle-all-33-types",
        "type": "collection",
        "entry": [{"resource": res} for res in REPRESENTATIVE_R4_RESOURCES.values()],
    }
    parsed = parse_fhir_bundle(
        json.dumps(bundle),
        source_name="Comprehensive Health System",
        profile_id=profile_id,
    )
    assert parsed["format"] == "fhir_r4"
    assert parsed["fhir_version"] == "4.0.1"
    assert parsed["summary"]["quarantined_count"] == 0
    assert parsed["summary"]["unsupported_count"] == 0
    assert parsed["summary"]["patient_context"]["status"] == "single_bundle_patient_verified"

    # 33 bundle entries + 1 synthesized batch Provenance = 34 records
    records = parsed["records"]
    assert len(records) == 34

    staged_types = {r["resource_type"] for r in records}
    assert staged_types == set(SUPPORTED_FHIR_RESOURCE_TYPES)

    # Verify scope routing: Coverage and ExplanationOfBenefit -> health.paperwork, all others -> health.clinical
    paperwork_records = [r for r in records if r["scope"] == "health.paperwork"]
    assert {r["resource_type"] for r in paperwork_records} == {"Coverage", "ExplanationOfBenefit"}
    assert parsed["summary"]["counts_by_scope"]["health.paperwork"] == 2
    assert parsed["summary"]["counts_by_scope"]["health.clinical"] == 32

    # Verify Observation multi-coding extraction (panel LOINC 85354-9 + components 8480-6 and 8462-4)
    obs_rec = next(r for r in records if r["resource_type"] == "Observation")
    obs_codes = {c["code"] for c in obs_rec["codings"]}
    assert {"85354-9", "8480-6", "8462-4", "vital-signs"}.issubset(obs_codes)

    # Verify verified patient reference was resolved to Patient/{profile_id} while preserving original mapping
    assert obs_rec["data"]["subject"]["reference"] == f"Patient/{profile_id}"
    mappings = obs_rec["data"]["_carefold_provenance"]["source_identity_mappings"]
    assert any(
        m["field"] == "subject"
        and m["source_reference"] == "Patient/pat-maya-1"
        and m["canonical_reference"] == f"Patient/{profile_id}"
        for m in mappings
    )
    # Original raw_resource still holds the unmodified source reference
    assert (
        obs_rec["data"]["_carefold_provenance"]["raw_resource"]["subject"]["reference"]
        == "Patient/pat-maya-1"
    )
    # Non-patient references on Observation remain untouched
    assert obs_rec["data"]["encounter"]["reference"] == "Encounter/enc-visit-1"
    assert obs_rec["data"]["performer"][0]["reference"] == "Practitioner/prac-cardio-1"
    assert obs_rec["data"]["device"]["reference"] == "Device/dev-bp-cuff-1"


def test_bundle_reference_resolution_urn_uuid_fullurl_and_contained():
    """Verifies resolution of urn:uuid fullUrls, absolute fullUrls, #contained resources, and external refs."""
    pat_uuid = "urn:uuid:11111111-2222-4333-8444-555555555555"
    enc_uuid = "urn:uuid:aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    prac_url = "https://fhir.hospital.example.org/r4/Practitioner/prac-99"
    profile_id = "prof-target-001"

    bundle = {
        "resourceType": "Bundle",
        "id": "bundle-ref-resolution",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": pat_uuid,
                "resource": {
                    "resourceType": "Patient",
                    "name": [{"family": "Patel", "given": ["Maya"]}],
                    "birthDate": "1988-11-23",
                },
            },
            {
                "fullUrl": enc_uuid,
                "resource": {
                    "resourceType": "Encounter",
                    "status": "finished",
                    "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
                    "subject": {"reference": pat_uuid},
                    "period": {"start": "2026-04-01T09:00:00Z"},
                },
            },
            {
                "fullUrl": prac_url,
                "resource": {
                    "resourceType": "Practitioner",
                    "id": "prac-99",
                    "name": [{"family": "Rivera", "given": ["Carlos"]}],
                },
            },
            {
                "fullUrl": "urn:uuid:99999999-8888-4777-8666-555555555555",
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "medreq-contained-1",
                    "status": "active",
                    "intent": "order",
                    "contained": [
                        {
                            "resourceType": "Medication",
                            "id": "inline-med-1",
                            "code": {
                                "coding": [
                                    {
                                        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                                        "code": "860975",
                                        "display": "Metformin hydrochloride 500 MG Oral Tablet",
                                    }
                                ]
                            },
                        }
                    ],
                    "medicationReference": {"reference": "#inline-med-1"},
                    "subject": {"reference": pat_uuid},
                    "encounter": {"reference": enc_uuid},
                    "requester": {"reference": prac_url},
                    "supportingInformation": [
                        {"reference": "https://external.registry.example.org/r4/Observation/ext-obs-42"}
                    ],
                    "authoredOn": "2026-04-01T09:30:00Z",
                },
            },
        ],
    }

    parsed = parse_fhir_bundle(json.dumps(bundle), profile_id=profile_id)
    assert parsed["summary"]["quarantined_count"] == 0
    records = parsed["records"]
    medreq = next(r for r in records if r["resource_type"] == "MedicationRequest")

    # 1. Patient urn:uuid resolved to canonical Patient/{profile_id}
    assert medreq["data"]["subject"]["reference"] == f"Patient/{profile_id}"

    # 2. Encounter urn:uuid resolved to Encounter/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee
    assert (
        medreq["data"]["encounter"]["reference"]
        == "Encounter/aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    )

    # 3. Absolute fullUrl matching bundle Practitioner entry resolved to Practitioner/prac-99
    assert medreq["data"]["requester"]["reference"] == "Practitioner/prac-99"

    # 4. Contained #inline-med-1 preserved in JSON and resolved in reference graph edges
    assert medreq["data"]["medicationReference"]["reference"] == "#inline-med-1"
    refs_by_field = {r["field"]: r for r in medreq["references"]}
    assert refs_by_field["medicationReference"]["target_type"] == "Medication"
    assert refs_by_field["medicationReference"]["target_id"] == "inline-med-1"
    assert refs_by_field["medicationReference"]["resolution_scope"] == "contained"
    assert refs_by_field["medicationReference"]["resolved"] is True

    # 5. External unresolved reference preserved without network fetch or patient re-attribution
    ext_ref = refs_by_field["supportingInformation"]
    assert ext_ref["target_type"] == "Observation"
    assert ext_ref["target_id"] == "ext-obs-42"
    assert ext_ref["is_external"] is True
    assert ext_ref["resolved"] is False
    assert (
        medreq["data"]["supportingInformation"][0]["reference"]
        == "https://external.registry.example.org/r4/Observation/ext-obs-42"
    )


def test_patient_reference_safety_quarantines_wrong_patient_and_multi_patient_bundles():
    """Verifies wrong-patient and ambiguous multi-patient records are quarantined rather than re-attributed."""
    # Case 1: Single Patient in bundle (pat-maya-1), but one Observation belongs to Patient/stranger-999
    mixed_bundle = {
        "resourceType": "Bundle",
        "id": "bundle-wrong-patient",
        "type": "collection",
        "entry": [
            {"resource": REPRESENTATIVE_R4_RESOURCES["Patient"]},
            {"resource": REPRESENTATIVE_R4_RESOURCES["Condition"]},
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-stranger-hiv",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "75622-1", "display": "HIV 1 RNA"}],
                        "text": "Sensitive Stranger Lab",
                    },
                    "subject": {
                        "reference": "Patient/stranger-999",
                        "display": "John Stranger SSN 999-00-1111",
                    },
                    "effectiveDateTime": "2026-03-01T10:00:00Z",
                }
            },
        ],
    }

    parsed = parse_fhir_bundle(json.dumps(mixed_bundle), profile_id="prof-maya")
    staged_ids = {r["source_id"] for r in parsed["records"]}
    assert "Patient:pat-maya-1" in staged_ids
    assert "Condition:cond-htn-1" in staged_ids
    assert "Observation:obs-stranger-hiv" not in staged_ids

    assert parsed["summary"]["quarantined_count"] == 1
    q_rec = parsed["quarantined_records"][0]
    assert q_rec["source_id"] == "Observation:obs-stranger-hiv"
    assert q_rec["reason_code"] == "wrong_patient_reference"
    # Verify PHI-safe diagnostics: free-text display/SSN must NEVER appear in diagnostics
    diag_blob = json.dumps(parsed["diagnostics"])
    assert "John Stranger" not in diag_blob
    assert "999-00-1111" not in diag_blob

    # Case 2: Multi-patient bundle with 2 distinct Patient resources and no expected_patient_id filter
    multi_patient_bundle = {
        "resourceType": "Bundle",
        "id": "bundle-two-patients",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-alice",
                    "name": [{"family": "Smith", "given": ["Alice"]}],
                }
            },
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "pat-bob",
                    "name": [{"family": "Jones", "given": ["Bob"]}],
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-alice-1",
                    "status": "final",
                    "code": {"text": "Heart rate"},
                    "subject": {"reference": "Patient/pat-alice"},
                }
            },
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bob-1",
                    "status": "final",
                    "code": {"text": "Heart rate"},
                    "subject": {"reference": "Patient/pat-bob"},
                }
            },
        ],
    }
    parsed_ambig = parse_fhir_bundle(json.dumps(multi_patient_bundle), profile_id="prof-alice")
    assert parsed_ambig["summary"]["patient_context"]["ambiguous_multi_patient"] is True
    assert parsed_ambig["summary"]["quarantined_count"] == 4
    # Only the synthesized batch Provenance record remains in records; zero patient records leaked
    assert [r["resource_type"] for r in parsed_ambig["records"]] == ["Provenance"]

    # When expected_patient_id="pat-alice" is explicitly supplied, Alice's records stage and Bob's quarantine
    parsed_disambig = parse_fhir_bundle(
        json.dumps(multi_patient_bundle),
        profile_id="prof-alice",
        expected_patient_id="pat-alice",
    )
    assert parsed_disambig["summary"]["quarantined_count"] == 2
    staged_disambig_ids = {r["source_id"] for r in parsed_disambig["records"]}
    assert "Patient:pat-alice" in staged_disambig_ids
    assert "Observation:obs-alice-1" in staged_disambig_ids
    assert "Patient:pat-bob" not in staged_disambig_ids
    assert "Observation:obs-bob-1" not in staged_disambig_ids


def test_malicious_and_non_r4_inputs_are_quarantined_with_phi_safe_diagnostics():
    """Verifies SSRF, javascript:/file:/data: URIs, path traversal, and R4B-only types are rejected."""
    adversarial_bundle = {
        "resourceType": "Bundle",
        "id": "bundle-adversarial",
        "type": "collection",
        "entry": [
            # 1. R4B-only resourceType (Citation is FHIR 4.3.0, not 4.0.1)
            {
                "resource": {
                    "resourceType": "Citation",
                    "id": "cit-r4b-1",
                    "status": "active",
                    "title": "Secret Patient Name Alice Cooper",
                }
            },
            # 2. Unsupported FHIR resourceType
            {
                "resource": {
                    "resourceType": "Account",
                    "id": "acct-1",
                    "status": "active",
                }
            },
            # 3. Malicious javascript: reference URI
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-xss-ref",
                    "status": "final",
                    "code": {"text": "Glucose"},
                    "subject": {"reference": "javascript:alert(document.cookie)"},
                }
            },
            # 4. Malicious file:// reference URI
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-file-ref",
                    "code": {"text": "Asthma"},
                    "subject": {"reference": "file:///etc/passwd"},
                }
            },
            # 5. Malicious SSRF cloud metadata reference URI
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": "doc-ssrf-ref",
                    "status": "current",
                    "subject": {"reference": "http://169.254.169.254/latest/meta-data/iam"},
                    "content": [{"attachment": {"contentType": "text/plain"}}],
                }
            },
            # 6. Path traversal in reference
            {
                "resource": {
                    "resourceType": "AllergyIntolerance",
                    "id": "allergy-trav-ref",
                    "code": {"text": "Latex"},
                    "patient": {"reference": "Patient/../../etc/shadow"},
                }
            },
            # 7. Structural datatype validation failure (valueQuantity.value is not a number)
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-bad-type",
                    "status": "final",
                    "code": {"text": "Potassium"},
                    "valueQuantity": {"value": "NOT_A_NUMBER_SECRET_PHI_VALUE", "unit": "mmol/L"},
                }
            },
            # 8. Dangling #contained reference
            {
                "resource": {
                    "resourceType": "MedicationRequest",
                    "id": "medreq-dangling-contained",
                    "status": "active",
                    "intent": "order",
                    "medicationReference": {"reference": "#nonexistent-contained-med"},
                    "subject": {"reference": "Patient/pat-maya-1"},
                }
            },
            # 9. Valid Observation that should still stage cleanly
            {
                "resource": {
                    "resourceType": "Observation",
                    "id": "obs-valid-1",
                    "status": "final",
                    "code": {
                        "coding": [{"system": "http://loinc.org", "code": "29463-7", "display": "Body Weight"}]
                    },
                    "subject": {"reference": "Patient/pat-maya-1"},
                    "valueQuantity": {"value": 64.2, "unit": "kg"},
                }
            },
        ],
    }

    parsed = parse_fhir_bundle(json.dumps(adversarial_bundle), profile_id="prof-maya")
    assert parsed["summary"]["quarantined_count"] == 8
    assert parsed["summary"]["unsupported_count"] == 2
    staged_non_prov = [r for r in parsed["records"] if r["resource_type"] != "Provenance"]
    assert len(staged_non_prov) == 1
    assert staged_non_prov[0]["source_id"] == "Observation:obs-valid-1"

    reason_codes = {q["source_id"]: q["reason_code"] for q in parsed["quarantined_records"]}
    assert reason_codes["Citation:cit-r4b-1"] == "r4b_only_resource_type"
    assert reason_codes["Account:acct-1"] == "unsupported_resource_type"
    assert reason_codes["Observation:obs-xss-ref"] == "malicious_reference_scheme_javascript"
    assert reason_codes["Condition:cond-file-ref"] == "malicious_reference_scheme_file"
    assert reason_codes["DocumentReference:doc-ssrf-ref"] == "malicious_reference_ssrf_host"
    assert reason_codes["AllergyIntolerance:allergy-trav-ref"] == "malicious_reference_traversal_or_control_char"
    assert reason_codes["Observation:obs-bad-type"] == "validation_error"
    assert reason_codes["MedicationRequest:medreq-dangling-contained"] == "dangling_contained_reference"

    # Ensure no PHI / invalid scalar values leak in diagnostic messages
    diag_json = json.dumps(parsed["diagnostics"])
    assert "Secret Patient Name Alice Cooper" not in diag_json
    assert "NOT_A_NUMBER_SECRET_PHI_VALUE" not in diag_json
    assert "document.cookie" not in diag_json


def test_declarative_fhirpath_evaluator_and_reference_classifier():
    """Tests evaluate_fhirpath union, where(), indexing, and classify_fhir_reference."""
    obs = REPRESENTATIVE_R4_RESOURCES["Observation"]
    assert evaluate_fhirpath(obs, "Observation.status") == ["final"]
    assert evaluate_fhirpath(obs, "Condition.status") == []
    assert evaluate_fhirpath(obs, "code.coding.code | component.code.coding.code") == [
        "85354-9",
        "8480-6",
        "8462-4",
    ]
    assert evaluate_fhirpath(obs, "component[1].valueQuantity.value") == [82]
    assert evaluate_fhirpath(obs, "component.code.coding.where(code='8480-6').display") == [
        "Systolic blood pressure"
    ]
    assert evaluate_fhirpath(obs, "component.code.coding.code.first()") == ["8480-6"]

    # Reference classifier checks
    assert classify_fhir_reference("Patient/pat-1")["kind"] == "relative"
    assert classify_fhir_reference("#med-1")["kind"] == "contained"
    assert classify_fhir_reference("urn:uuid:11111111-2222-4333-8444-555555555555")["kind"] == "urn_uuid"
    assert classify_fhir_reference("urn:oid:2.16.840.1.113883.4.1")["kind"] == "urn_oid"
    assert classify_fhir_reference("data:text/html,<script>alert(1)</script>")["is_malicious"] is True
    assert classify_fhir_reference("http://localhost:8000/Patient/1")["is_malicious"] is True

    # R4B-only resource types set is disjoint from supported R4 resource types
    assert SUPPORTED_FHIR_RESOURCE_TYPES.isdisjoint(R4B_ONLY_RESOURCE_TYPES)

    # Extract references excludes Reference.display to prevent PHI leakage into graph edges
    refs = extract_references(
        {
            "resourceType": "Observation",
            "status": "final",
            "code": {"text": "HR"},
            "subject": {"reference": "Patient/pat-1", "display": "Maya Patel"},
        },
        rtype="Observation",
    )
    assert len(refs) == 1
    assert "display" not in refs[0]
    assert "Maya Patel" not in json.dumps(refs)
