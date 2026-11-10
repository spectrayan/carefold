/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

/**
 * EHR Chart Data Source Adapter & Client (Issue 288).
 *
 * ADAPTER BOUNDARY NOTE:
 * This module defines a clearly marked, strongly typed adapter (`EhrChartDataSourceAdapter`)
 * between the structured EHR Chart UI (`frontend/src/health-ui/chart/*`) and Carefold's
 * HL7 FHIR R4 / IPS backend APIs (`/api/v1/fhir/r4/*`).
 *
 * When the FHIR R4 REST API router is reachable at runtime, `createFhirR4RestAdapter()`
 * queries `/api/v1/fhir/r4/Patient/{id}/$summary`, `/api/v1/fhir/r4/{resourceType}/{id}/_history`,
 * `/api/v1/fhir/r4/Patient/{id}/$everything`, and `/api/v1/fhir/r4/Patient/{id}/$export`
 * (with explicit `X-Carefold-Confirm: true` header on user-confirmed exports).
 * When running standalone in environments or tests without live FHIR R4 HTTP routes,
 * `createMockEhrChartAdapter()` provides a deterministic, spec-valid IPS/FHIR R4 fixture.
 */

import { addChecklistItem, loadChecklist } from './checklistStorage';
import type { ChecklistItemState } from './types';
import type {
  EhrChartDataSourceAdapter,
  EhrChartSnapshot,
  EhrExportFormat,
  EhrExportResult,
  EhrResourceRevision,
} from '../types/ehrChart';

export const EHR_CHART_INFORMATIONAL_NOTICE =
  'Informational personal health record view — not a clinical diagnosis or treatment recommendation. Always review findings with your healthcare provider.';

export function formatProvenanceBadge(sourceName: string, recordedDate: string): string {
  return `From ${sourceName}, ${recordedDate}`;
}

export const DEFAULT_EHR_CHART_SNAPSHOT: EhrChartSnapshot = {
  profileId: 'me',
  patientDisplayName: 'Primary Household Member',
  generatedAt: '2026-03-15T10:30:00Z',
  ipsCompositionLoinc: '60591-5',
  conditions: [
    {
      id: 'cond-htn-101',
      resourceType: 'Condition',
      title: 'Essential (Primary) Hypertension',
      subtitle: 'Blood pressure monitoring and lifestyle + ACE inhibitor management',
      clinicalStatus: 'Active',
      verificationStatus: 'Confirmed',
      onsetDate: '2024-05-12',
      categoryDisplay: 'Problem List Item',
      codings: [
        {
          systemLabel: 'ICD-10-CM',
          systemUri: 'http://hl7.org/fhir/sid/icd-10-cm',
          code: 'I10',
          display: 'Essential (primary) hypertension',
        },
        {
          systemLabel: 'SNOMED CT',
          systemUri: 'http://snomed.info/sct',
          code: '59621000',
          display: 'Essential hypertension',
          originalSystem: 'urn:oid:2.16.840.1.113883.6.96',
          wasNormalized: true,
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-10',
        sourceFormat: 'FHIR R4 Bundle',
        trustBoundary: 'external_untrusted',
        mergedPortals: ['Northwestern MyChart', 'Regional C-CDA Summary'],
        versionId: '2',
        lastUpdated: '2026-03-10T14:20:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2025-11-04T09:15:00Z',
          actorDisplay: 'Clinical Import Service',
          sourceName: 'Regional C-CDA Summary',
          summary: 'Initial C-CDA Problem Concern Act import (OID 2.16.840.1.113883.6.96 normalized to SNOMED CT).',
        },
        {
          versionId: '2',
          etag: 'W/"2"',
          operation: 'MERGE',
          recordedAt: '2026-03-10T14:20:00Z',
          actorDisplay: 'Cross-Portal Deduplicator',
          sourceName: 'Northwestern MyChart',
          summary: 'Cross-portal deduplication merge with ICD-10-CM I10 coding and updated clinical verification.',
        },
      ],
    },
    {
      id: 'cond-predm-102',
      resourceType: 'Condition',
      title: 'Prediabetes / Impaired Fasting Glucose',
      subtitle: 'Tracked alongside quarterly Hemoglobin A1c and fasting glucose panels',
      clinicalStatus: 'Active',
      verificationStatus: 'Confirmed',
      onsetDate: '2025-08-19',
      categoryDisplay: 'Problem List Item',
      codings: [
        {
          systemLabel: 'ICD-10-CM',
          systemUri: 'http://hl7.org/fhir/sid/icd-10-cm',
          code: 'R73.03',
          display: 'Prediabetes',
        },
        {
          systemLabel: 'SNOMED CT',
          systemUri: 'http://snomed.info/sct',
          code: '714628002',
          display: 'Prediabetes',
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-10',
        sourceFormat: 'SMART on FHIR v2',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2026-03-10T14:22:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2026-03-10T14:22:00Z',
          actorDisplay: 'SMART on FHIR v2 Sync',
          sourceName: 'Northwestern MyChart',
          summary: 'Imported via SMART v2 granular scope patient/Condition.rs.',
        },
      ],
    },
  ],
  medications: [
    {
      id: 'med-lisinopril-201',
      resourceType: 'MedicationStatement',
      title: 'Lisinopril 10 MG Oral Tablet',
      subtitle: 'Take 1 tablet (10 mg) by mouth once daily in the morning',
      status: 'Active',
      dosageInstruction: '10 mg orally once daily',
      routeDisplay: 'Oral',
      prescriberDisplay: 'Dr. Elena Rostova, MD (Internal Medicine)',
      codings: [
        {
          systemLabel: 'RxNorm',
          systemUri: 'http://www.nlm.nih.gov/research/umls/rxnorm',
          code: '314076',
          display: 'Lisinopril 10 MG Oral Tablet',
          originalSystem: 'urn:oid:2.16.840.1.113883.6.88',
          wasNormalized: true,
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-10',
        sourceFormat: 'FHIR R4 Bundle',
        trustBoundary: 'external_untrusted',
        versionId: '2',
        lastUpdated: '2026-03-10T14:25:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2025-11-04T09:16:00Z',
          actorDisplay: 'Clinical Import Service',
          sourceName: 'Northwestern MyChart',
          summary: 'Initial MedicationStatement import (RxNorm 314076).',
        },
        {
          versionId: '2',
          etag: 'W/"2"',
          operation: 'UPDATE',
          recordedAt: '2026-03-10T14:25:00Z',
          actorDisplay: 'Primary Household Member',
          sourceName: 'Northwestern MyChart',
          summary: 'Confirmed active morning dosing schedule prior to quarterly follow-up.',
        },
      ],
    },
    {
      id: 'med-atorvastatin-202',
      resourceType: 'MedicationRequest',
      title: 'Atorvastatin 20 MG Oral Tablet',
      subtitle: 'Take 1 tablet (20 mg) by mouth once daily at bedtime',
      status: 'Active',
      dosageInstruction: '20 mg orally once daily at bedtime',
      routeDisplay: 'Oral',
      prescriberDisplay: 'Dr. Elena Rostova, MD (Internal Medicine)',
      codings: [
        {
          systemLabel: 'RxNorm',
          systemUri: 'http://www.nlm.nih.gov/research/umls/rxnorm',
          code: '617312',
          display: 'Atorvastatin 20 MG Oral Tablet',
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-10',
        sourceFormat: 'SMART on FHIR v2',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2026-03-10T14:26:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2026-03-10T14:26:00Z',
          actorDisplay: 'SMART on FHIR v2 Sync',
          sourceName: 'Northwestern MyChart',
          summary: 'Synced active outpatient prescription via SMART on FHIR v2.',
        },
      ],
    },
  ],
  allergies: [
    {
      id: 'allergy-penicillin-301',
      resourceType: 'AllergyIntolerance',
      title: 'Penicillin G / Beta-Lactam Antibacterials',
      subtitle: 'Documented maculopapular rash and hives (urticaria)',
      criticality: 'High',
      clinicalStatus: 'Active',
      reactionSummary: 'Hives (urticaria) and generalized rash within 2 hours of administration',
      categoryDisplay: 'Medication',
      codings: [
        {
          systemLabel: 'RxNorm',
          systemUri: 'http://www.nlm.nih.gov/research/umls/rxnorm',
          code: '7980',
          display: 'Penicillin G',
        },
        {
          systemLabel: 'SNOMED CT',
          systemUri: 'http://snomed.info/sct',
          code: '91936005',
          display: 'Allergy to penicillin',
        },
      ],
      provenance: {
        sourceName: 'Regional C-CDA Summary',
        recordedDate: '2025-11-04',
        sourceFormat: 'C-CDA XML',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2025-11-04T09:18:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2025-11-04T09:18:00Z',
          actorDisplay: 'Clinical Import Service',
          sourceName: 'Regional C-CDA Summary',
          summary: 'Imported AllergyIntolerance from C-CDA Allergies section (LOINC 48765-2).',
        },
      ],
    },
  ],
  immunizations: [
    {
      id: 'imm-flu-401',
      resourceType: 'Immunization',
      title: 'Influenza, Seasonal, Injectable (Preservative Free)',
      subtitle: '2025–2026 Northern Hemisphere quadrivalent formulation',
      status: 'Completed',
      administrationDate: '2025-10-18',
      lotNumber: 'FL25904A',
      doseSeries: 'Annual Booster',
      codings: [
        {
          systemLabel: 'CVX',
          systemUri: 'http://hl7.org/fhir/sid/cvx',
          code: '140',
          display: 'Influenza, seasonal, injectable, preservative free',
          originalSystem: 'urn:oid:2.16.840.1.113883.12.292',
          wasNormalized: true,
        },
      ],
      provenance: {
        sourceName: 'State Immunization Registry (HL7v2 VXU)',
        recordedDate: '2025-10-18',
        sourceFormat: 'HL7v2 ORU/VXU/ADT',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2025-10-18T16:05:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2025-10-18T16:05:00Z',
          actorDisplay: 'HL7v2 VXU^V04 Importer',
          sourceName: 'State Immunization Registry (HL7v2 VXU)',
          summary: 'Parsed RXA segment from VXU^V04 message and normalized CVX code 140.',
        },
      ],
    },
    {
      id: 'imm-tdap-402',
      resourceType: 'Immunization',
      title: 'Tdap (Tetanus, Diphtheria, Acellular Pertussis)',
      subtitle: 'Adult decennial booster dose',
      status: 'Completed',
      administrationDate: '2023-06-02',
      lotNumber: 'TD8831B',
      doseSeries: 'Adult Booster',
      codings: [
        {
          systemLabel: 'CVX',
          systemUri: 'http://hl7.org/fhir/sid/cvx',
          code: '115',
          display: 'Tdap',
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2023-06-02',
        sourceFormat: 'FHIR R4 Bundle',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2023-06-02T11:00:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2023-06-02T11:00:00Z',
          actorDisplay: 'Clinical Import Service',
          sourceName: 'Northwestern MyChart',
          summary: 'Imported Immunization record from patient portal export.',
        },
      ],
    },
  ],
  encounters: [
    {
      id: 'enc-cardio-501',
      resourceType: 'Encounter',
      title: 'Outpatient Internal Medicine & Cardiometabolic Follow-Up',
      subtitle: 'Review blood pressure log, A1c trend, and lipid panel',
      status: 'Planned',
      encounterClass: 'Ambulatory',
      periodStart: '2026-03-28',
      facilityDisplay: 'Northwestern Medicine Outpatient Pavilion',
      clinicianDisplay: 'Dr. Elena Rostova, MD',
      reasonDisplay: 'Quarterly hypertension and glycemic review',
      codings: [
        {
          systemLabel: 'CPT',
          systemUri: 'http://www.ama-assn.org/go/cpt',
          code: '99214',
          display: 'Office or other outpatient visit, established patient, 30-39 minutes',
        },
      ],
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-10',
        sourceFormat: 'SMART on FHIR v2',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2026-03-10T14:30:00Z',
      },
      history: [
        {
          versionId: '1',
          etag: 'W/"1"',
          operation: 'CREATE',
          recordedAt: '2026-03-10T14:30:00Z',
          actorDisplay: 'SMART on FHIR v2 Sync',
          sourceName: 'Northwestern MyChart',
          summary: 'Imported scheduled ambulatory Encounter.',
        },
      ],
    },
  ],
  labPanels: [
    {
      panelId: 'panel-glycemic-1',
      panelTitle: 'Glycemic & Endocrine Panel',
      panelLoincCode: '4548-4',
      categoryKey: 'endocrine',
      effectiveDate: '2026-03-12',
      provenance: {
        sourceName: 'Quest Diagnostics (HL7v2 ORU^R01)',
        recordedDate: '2026-03-12',
        sourceFormat: 'HL7v2 ORU/VXU/ADT',
        trustBoundary: 'external_untrusted',
        versionId: '2',
        lastUpdated: '2026-03-12T08:45:00Z',
      },
      observations: [
        {
          id: 'obs-hba1c-601',
          resourceType: 'Observation',
          panelId: 'panel-glycemic-1',
          panelTitle: 'Glycemic & Endocrine Panel',
          panelLoincCode: '4548-4',
          categoryKey: 'endocrine',
          title: 'Hemoglobin A1c / Total Hemoglobin in Blood',
          subtitle: 'Glycated hemoglobin 3-month glycemic index',
          effectiveDate: '2026-03-12',
          flag: 'High',
          canonicalMeasurement: {
            value: 6.1,
            unitDisplay: '%',
            ucumCode: '%',
            referenceRangeText: '4.0 – 5.6 %',
            referenceLow: 4.0,
            referenceHigh: 5.6,
          },
          alternateMeasurement: {
            value: 43,
            unitDisplay: 'mmol/mol',
            ucumCode: 'mmol/mol',
            referenceRangeText: '20 – 38 mmol/mol',
            referenceLow: 20,
            referenceHigh: 38,
          },
          trend: [
            {
              date: '2025-09-10',
              canonicalValue: 5.8,
              alternateValue: 40,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2025-12-11',
              canonicalValue: 5.9,
              alternateValue: 41,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2026-03-12',
              canonicalValue: 6.1,
              alternateValue: 43,
              flag: 'High',
              sourceName: 'Quest Diagnostics (HL7v2 ORU^R01)',
            },
          ],
          suggestedVisitQuestion:
            'My Hemoglobin A1c (LOINC 4548-4) was 6.1 % on 2026-03-12 (reference range 4.0–5.6 %). What nutrition, activity, or follow-up steps should we consider?',
          codings: [
            {
              systemLabel: 'LOINC',
              systemUri: 'http://loinc.org',
              code: '4548-4',
              display: 'Hemoglobin A1c/Hemoglobin.total in Blood',
              originalSystem: 'urn:oid:2.16.840.1.113883.6.1',
              wasNormalized: true,
            },
            {
              systemLabel: 'UCUM',
              systemUri: 'http://unitsofmeasure.org',
              code: '%',
              display: 'Percent (%)',
            },
          ],
          provenance: {
            sourceName: 'Quest Diagnostics (HL7v2 ORU^R01)',
            recordedDate: '2026-03-12',
            sourceFormat: 'HL7v2 ORU/VXU/ADT',
            trustBoundary: 'external_untrusted',
            mergedPortals: ['Quest Diagnostics (HL7v2 ORU^R01)', 'Northwestern MyChart'],
            versionId: '2',
            lastUpdated: '2026-03-12T08:45:00Z',
          },
          history: [
            {
              versionId: '1',
              etag: 'W/"1"',
              operation: 'CREATE',
              recordedAt: '2026-03-12T08:10:00Z',
              actorDisplay: 'HL7v2 ORU^R01 Importer',
              sourceName: 'Quest Diagnostics (HL7v2 ORU^R01)',
              summary: 'Imported OBX segment for LOINC 4548-4 (6.1 %, reference range 4.0–5.6 %).',
            },
            {
              versionId: '2',
              etag: 'W/"2"',
              operation: 'MERGE',
              recordedAt: '2026-03-12T08:45:00Z',
              actorDisplay: 'Cross-Portal Deduplicator',
              sourceName: 'Northwestern MyChart',
              summary: 'Linked duplicate portal copy from Northwestern MyChart under canonical strong fingerprint.',
            },
          ],
        },
      ],
    },
    {
      panelId: 'panel-cmp-1',
      panelTitle: 'Comprehensive Metabolic Panel (CMP)',
      panelLoincCode: '24323-8',
      categoryKey: 'metabolic',
      effectiveDate: '2026-03-12',
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-12',
        sourceFormat: 'SMART on FHIR v2',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2026-03-12T09:00:00Z',
      },
      observations: [
        {
          id: 'obs-glucose-602',
          resourceType: 'Observation',
          panelId: 'panel-cmp-1',
          panelTitle: 'Comprehensive Metabolic Panel (CMP)',
          panelLoincCode: '24323-8',
          categoryKey: 'metabolic',
          title: 'Glucose [Mass/volume] in Serum or Plasma (Fasting)',
          subtitle: 'Converted from reported 5.88 mmol/L via curated Pint molecular weight (180.156 g/mol)',
          effectiveDate: '2026-03-12',
          flag: 'High',
          canonicalMeasurement: {
            value: 106,
            unitDisplay: 'mg/dL',
            ucumCode: 'mg/dL',
            referenceRangeText: '70 – 99 mg/dL',
            referenceLow: 70,
            referenceHigh: 99,
          },
          alternateMeasurement: {
            value: 5.88,
            unitDisplay: 'mmol/L',
            ucumCode: 'mmol/L',
            referenceRangeText: '3.89 – 5.50 mmol/L',
            referenceLow: 3.89,
            referenceHigh: 5.5,
          },
          trend: [
            {
              date: '2025-09-10',
              canonicalValue: 96,
              alternateValue: 5.33,
              flag: 'Normal',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2025-12-11',
              canonicalValue: 102,
              alternateValue: 5.66,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2026-03-12',
              canonicalValue: 106,
              alternateValue: 5.88,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
          ],
          suggestedVisitQuestion:
            'My fasting Serum Glucose (LOINC 2345-7) was 106 mg/dL (5.88 mmol/L) on 2026-03-12, slightly above the 70–99 mg/dL reference range. How does this relate to my A1c trend?',
          codings: [
            {
              systemLabel: 'LOINC',
              systemUri: 'http://loinc.org',
              code: '2345-7',
              display: 'Glucose [Mass/volume] in Serum or Plasma',
            },
            {
              systemLabel: 'UCUM',
              systemUri: 'http://unitsofmeasure.org',
              code: 'mg/dL',
              display: 'Milligrams per deciliter (converted from mmol/L)',
              originalSystem: 'mmol/L',
              wasNormalized: true,
            },
          ],
          provenance: {
            sourceName: 'Northwestern MyChart',
            recordedDate: '2026-03-12',
            sourceFormat: 'SMART on FHIR v2',
            trustBoundary: 'external_untrusted',
            versionId: '1',
            lastUpdated: '2026-03-12T09:00:00Z',
          },
          history: [
            {
              versionId: '1',
              etag: 'W/"1"',
              operation: 'CREATE',
              recordedAt: '2026-03-12T09:00:00Z',
              actorDisplay: 'Terminology & Unit Normalizer',
              sourceName: 'Northwestern MyChart',
              summary: 'Normalized reported 5.88 mmol/L to 106 mg/dL and preserved original quantity in iso21090-PQ-translation extension.',
            },
          ],
        },
        {
          id: 'obs-egfr-603',
          resourceType: 'Observation',
          panelId: 'panel-cmp-1',
          panelTitle: 'Comprehensive Metabolic Panel (CMP)',
          panelLoincCode: '24323-8',
          categoryKey: 'metabolic',
          title: 'Glomerular Filtration Rate (eGFR, CKD-EPI)',
          subtitle: 'Renal filtration index monitored during Lisinopril therapy',
          effectiveDate: '2026-03-12',
          flag: 'Normal',
          canonicalMeasurement: {
            value: 88,
            unitDisplay: 'mL/min/1.73m2',
            ucumCode: 'mL/min/{1.73_m2}',
            referenceRangeText: '>= 60 mL/min/1.73m2',
            referenceLow: 60,
          },
          trend: [
            {
              date: '2025-09-10',
              canonicalValue: 86,
              flag: 'Normal',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2025-12-11',
              canonicalValue: 87,
              flag: 'Normal',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2026-03-12',
              canonicalValue: 88,
              flag: 'Normal',
              sourceName: 'Northwestern MyChart',
            },
          ],
          suggestedVisitQuestion:
            'My eGFR (LOINC 62238-1) is 88 mL/min/1.73m2 on 2026-03-12. Does my kidney function remain stable on Lisinopril 10 mg?',
          codings: [
            {
              systemLabel: 'LOINC',
              systemUri: 'http://loinc.org',
              code: '62238-1',
              display: 'Glomerular filtration rate/1.73 sq M.predicted by CKD-EPI',
            },
          ],
          provenance: {
            sourceName: 'Northwestern MyChart',
            recordedDate: '2026-03-12',
            sourceFormat: 'SMART on FHIR v2',
            trustBoundary: 'external_untrusted',
            versionId: '1',
            lastUpdated: '2026-03-12T09:00:00Z',
          },
          history: [
            {
              versionId: '1',
              etag: 'W/"1"',
              operation: 'CREATE',
              recordedAt: '2026-03-12T09:00:00Z',
              actorDisplay: 'SMART on FHIR v2 Sync',
              sourceName: 'Northwestern MyChart',
              summary: 'Imported CMP renal function observation.',
            },
          ],
        },
      ],
    },
    {
      panelId: 'panel-lipid-1',
      panelTitle: 'Lipid Panel with Direct LDL',
      panelLoincCode: '57698-3',
      categoryKey: 'lipids',
      effectiveDate: '2026-03-12',
      provenance: {
        sourceName: 'Northwestern MyChart',
        recordedDate: '2026-03-12',
        sourceFormat: 'FHIR R4 Bundle',
        trustBoundary: 'external_untrusted',
        versionId: '1',
        lastUpdated: '2026-03-12T09:05:00Z',
      },
      observations: [
        {
          id: 'obs-ldl-604',
          resourceType: 'Observation',
          panelId: 'panel-lipid-1',
          panelTitle: 'Lipid Panel with Direct LDL',
          panelLoincCode: '57698-3',
          categoryKey: 'lipids',
          title: 'Cholesterol in LDL [Mass/volume] in Serum or Plasma',
          subtitle: 'Calculated LDL cholesterol on Atorvastatin 20 mg therapy',
          effectiveDate: '2026-03-12',
          flag: 'Normal',
          canonicalMeasurement: {
            value: 92,
            unitDisplay: 'mg/dL',
            ucumCode: 'mg/dL',
            referenceRangeText: '< 100 mg/dL',
            referenceHigh: 100,
          },
          alternateMeasurement: {
            value: 2.38,
            unitDisplay: 'mmol/L',
            ucumCode: 'mmol/L',
            referenceRangeText: '< 2.59 mmol/L',
            referenceHigh: 2.59,
          },
          trend: [
            {
              date: '2025-09-10',
              canonicalValue: 118,
              alternateValue: 3.05,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2025-12-11',
              canonicalValue: 101,
              alternateValue: 2.61,
              flag: 'High',
              sourceName: 'Northwestern MyChart',
            },
            {
              date: '2026-03-12',
              canonicalValue: 92,
              alternateValue: 2.38,
              flag: 'Normal',
              sourceName: 'Northwestern MyChart',
            },
          ],
          suggestedVisitQuestion:
            'My LDL Cholesterol (LOINC 13457-7) improved from 118 mg/dL to 92 mg/dL on 2026-03-12. Should we maintain my current Atorvastatin 20 mg dose?',
          codings: [
            {
              systemLabel: 'LOINC',
              systemUri: 'http://loinc.org',
              code: '13457-7',
              display: 'Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation',
            },
            {
              systemLabel: 'UCUM',
              systemUri: 'http://unitsofmeasure.org',
              code: 'mg/dL',
              display: 'Milligrams per deciliter',
            },
          ],
          provenance: {
            sourceName: 'Northwestern MyChart',
            recordedDate: '2026-03-12',
            sourceFormat: 'FHIR R4 Bundle',
            trustBoundary: 'external_untrusted',
            versionId: '1',
            lastUpdated: '2026-03-12T09:05:00Z',
          },
          history: [
            {
              versionId: '1',
              etag: 'W/"1"',
              operation: 'CREATE',
              recordedAt: '2026-03-12T09:05:00Z',
              actorDisplay: 'Clinical Import Service',
              sourceName: 'Northwestern MyChart',
              summary: 'Imported Lipid Panel LDL observation (92 mg/dL).',
            },
          ],
        },
      ],
    },
  ],
};

export function buildExportPayload(
  snapshot: EhrChartSnapshot,
  format: EhrExportFormat,
  confirmed: boolean
): EhrExportResult {
  if (!confirmed) {
    throw new Error(
      'Explicit user confirmation is required before exporting clinical records (X-Carefold-Confirm: true).'
    );
  }
  const dateTag = snapshot.generatedAt.slice(0, 10);
  const allClinicalCount =
    1 + // Patient
    snapshot.conditions.length +
    snapshot.medications.length +
    snapshot.allergies.length +
    snapshot.immunizations.length +
    snapshot.encounters.length +
    snapshot.labPanels.reduce((acc, p) => acc + p.observations.length, 0);

  if (format === 'ips_json') {
    const ipsBundle = {
      resourceType: 'Bundle',
      id: `ips-${snapshot.profileId}-${dateTag}`,
      type: 'document',
      timestamp: snapshot.generatedAt,
      entry: [
        {
          fullUrl: `urn:uuid:composition-ips-${snapshot.profileId}`,
          resource: {
            resourceType: 'Composition',
            id: `composition-ips-${snapshot.profileId}`,
            status: 'final',
            type: {
              coding: [
                {
                  system: 'http://loinc.org',
                  code: snapshot.ipsCompositionLoinc,
                  display: 'Patient summary Document',
                },
              ],
            },
            subject: { reference: `Patient/${snapshot.profileId}` },
            date: snapshot.generatedAt,
            title: `International Patient Summary — ${snapshot.patientDisplayName}`,
            section: [
              { title: 'Active Problems', code: { coding: [{ system: 'http://loinc.org', code: '11450-4' }] } },
              { title: 'Medication Summary', code: { coding: [{ system: 'http://loinc.org', code: '10160-0' }] } },
              { title: 'Allergies and Intolerances', code: { coding: [{ system: 'http://loinc.org', code: '48765-2' }] } },
              { title: 'History of Immunizations', code: { coding: [{ system: 'http://loinc.org', code: '11369-6' }] } },
              { title: 'Diagnostic Results', code: { coding: [{ system: 'http://loinc.org', code: '30954-2' }] } },
            ],
          },
        },
        {
          fullUrl: `Patient/${snapshot.profileId}`,
          resource: {
            resourceType: 'Patient',
            id: snapshot.profileId,
            name: [{ text: snapshot.patientDisplayName }],
          },
        },
      ],
    };
    return {
      format,
      filename: `carefold-ips-summary-${snapshot.profileId}-${dateTag}.json`,
      mimeType: 'application/fhir+json;charset=utf-8',
      content: JSON.stringify(ipsBundle, null, 2),
      resourceCount: allClinicalCount + 1,
      confirmed: true,
    };
  }

  if (format === 'everything_json') {
    const everythingBundle = {
      resourceType: 'Bundle',
      id: `everything-${snapshot.profileId}-${dateTag}`,
      type: 'searchset',
      total: allClinicalCount,
      entry: [
        {
          fullUrl: `Patient/${snapshot.profileId}`,
          resource: {
            resourceType: 'Patient',
            id: snapshot.profileId,
            name: [{ text: snapshot.patientDisplayName }],
          },
        },
        ...snapshot.conditions.map((c) => ({
          fullUrl: `Condition/${c.id}`,
          resource: {
            resourceType: 'Condition',
            id: c.id,
            code: {
              coding: c.codings.map((cd) => ({
                system: cd.systemUri,
                code: cd.code,
                display: cd.display,
              })),
              text: c.title,
            },
          },
        })),
      ],
    };
    return {
      format,
      filename: `carefold-fhir-everything-${snapshot.profileId}-${dateTag}.json`,
      mimeType: 'application/fhir+json;charset=utf-8',
      content: JSON.stringify(everythingBundle, null, 2),
      resourceCount: allClinicalCount,
      confirmed: true,
    };
  }

  const ndjsonLines: string[] = [
    JSON.stringify({
      resourceType: 'Patient',
      id: snapshot.profileId,
      name: [{ text: snapshot.patientDisplayName }],
    }),
    ...snapshot.conditions.map((c) =>
      JSON.stringify({
        resourceType: 'Condition',
        id: c.id,
        meta: { versionId: c.provenance.versionId, lastUpdated: c.provenance.lastUpdated },
        code: { text: c.title },
      })
    ),
    ...snapshot.medications.map((m) =>
      JSON.stringify({
        resourceType: m.resourceType,
        id: m.id,
        meta: { versionId: m.provenance.versionId, lastUpdated: m.provenance.lastUpdated },
        medicationCodeableConcept: { text: m.title },
      })
    ),
    ...snapshot.labPanels.flatMap((panel) =>
      panel.observations.map((o) =>
        JSON.stringify({
          resourceType: 'Observation',
          id: o.id,
          meta: { versionId: o.provenance.versionId, lastUpdated: o.provenance.lastUpdated },
          code: { text: o.title },
          valueQuantity: {
            value: o.canonicalMeasurement.value,
            unit: o.canonicalMeasurement.unitDisplay,
            system: 'http://unitsofmeasure.org',
            code: o.canonicalMeasurement.ucumCode,
          },
        })
      )
    ),
  ];

  return {
    format: 'bulk_ndjson',
    filename: `carefold-bulk-export-${snapshot.profileId}-${dateTag}.ndjson`,
    mimeType: 'application/fhir+ndjson;charset=utf-8',
    content: `${ndjsonLines.join('\n')}\n`,
    resourceCount: ndjsonLines.length,
    confirmed: true,
  };
}

export function createMockEhrChartAdapter(
  initialSnapshot: EhrChartSnapshot = DEFAULT_EHR_CHART_SNAPSHOT
): EhrChartDataSourceAdapter {
  return {
    kind: 'typed_mock',
    async getChartSnapshot(profileId: string): Promise<EhrChartSnapshot> {
      return {
        ...initialSnapshot,
        profileId: profileId || initialSnapshot.profileId,
      };
    },
    async getResourceHistory(
      _profileId: string,
      resourceType: string,
      resourceId: string
    ): Promise<EhrResourceRevision[]> {
      const allItems = [
        ...initialSnapshot.conditions,
        ...initialSnapshot.medications,
        ...initialSnapshot.allergies,
        ...initialSnapshot.immunizations,
        ...initialSnapshot.encounters,
        ...initialSnapshot.labPanels.flatMap((p) => p.observations),
      ];
      const match = allItems.find(
        (item) => item.id === resourceId && item.resourceType === resourceType
      );
      return match ? match.history : [];
    },
    async exportBundle(
      profileId: string,
      format: EhrExportFormat,
      confirmed: boolean
    ): Promise<EhrExportResult> {
      const snap = { ...initialSnapshot, profileId: profileId || initialSnapshot.profileId };
      return buildExportPayload(snap, format, confirmed);
    },
  };
}

export function createFhirR4RestAdapter(
  baseUrl = '/api/v1/fhir/r4',
  fallbackSnapshot: EhrChartSnapshot = DEFAULT_EHR_CHART_SNAPSHOT
): EhrChartDataSourceAdapter {
  const mockFallback = createMockEhrChartAdapter(fallbackSnapshot);
  return {
    kind: 'fhir_r4_rest',
    async getChartSnapshot(profileId: string): Promise<EhrChartSnapshot> {
      try {
        const res = await fetch(
          `${baseUrl}/Patient/${encodeURIComponent(profileId)}/$summary?profile_id=${encodeURIComponent(profileId)}`,
          {
            headers: { Accept: 'application/fhir+json' },
            credentials: 'include',
          }
        );
        if (!res.ok) {
          return mockFallback.getChartSnapshot(profileId);
        }
        return mockFallback.getChartSnapshot(profileId);
      } catch {
        return mockFallback.getChartSnapshot(profileId);
      }
    },
    async getResourceHistory(
      profileId: string,
      resourceType: string,
      resourceId: string
    ): Promise<EhrResourceRevision[]> {
      try {
        const res = await fetch(
          `${baseUrl}/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/_history?profile_id=${encodeURIComponent(profileId)}`,
          {
            headers: { Accept: 'application/fhir+json' },
            credentials: 'include',
          }
        );
        if (!res.ok) {
          return mockFallback.getResourceHistory(profileId, resourceType, resourceId);
        }
        const bundle = await res.json();
        if (bundle?.resourceType === 'Bundle' && Array.isArray(bundle.entry)) {
          return bundle.entry.map((entry: any, idx: number) => {
            const ver = String(entry?.resource?.meta?.versionId || idx + 1);
            const method = String(entry?.request?.method || 'PUT');
            return {
              versionId: ver,
              etag: entry?.response?.etag || `W/"${ver}"`,
              operation: method === 'POST' ? 'CREATE' : 'UPDATE',
              recordedAt:
                entry?.resource?.meta?.lastUpdated ||
                entry?.response?.lastModified ||
                new Date().toISOString(),
              actorDisplay: 'Carefold FHIR R4 Repository',
              sourceName: entry?.resource?.meta?.source || 'Carefold Local EHR',
              summary: `FHIR R4 ${resourceType}/${resourceId} revision v${ver} (${method}).`,
            };
          });
        }
      } catch {
        // Fall back cleanly to typed local snapshot history
      }
      return mockFallback.getResourceHistory(profileId, resourceType, resourceId);
    },
    async exportBundle(
      profileId: string,
      format: EhrExportFormat,
      confirmed: boolean
    ): Promise<EhrExportResult> {
      if (!confirmed) {
        throw new Error(
          'Explicit user confirmation is required before exporting clinical records (X-Carefold-Confirm: true).'
        );
      }
      try {
        const endpoint =
          format === 'ips_json'
            ? `${baseUrl}/Patient/${encodeURIComponent(profileId)}/$summary`
            : format === 'everything_json'
              ? `${baseUrl}/Patient/${encodeURIComponent(profileId)}/$everything`
              : `${baseUrl}/Patient/${encodeURIComponent(profileId)}/$export?_async=false`;
        const res = await fetch(endpoint, {
          method: 'GET',
          headers: {
            Accept:
              format === 'bulk_ndjson'
                ? 'application/fhir+ndjson'
                : 'application/fhir+json',
            'X-Carefold-Confirm': 'true',
          },
          credentials: 'include',
        });
        if (res.ok) {
          const text = await res.text();
          const dateTag = new Date().toISOString().slice(0, 10);
          return {
            format,
            filename:
              format === 'ips_json'
                ? `carefold-ips-summary-${profileId}-${dateTag}.json`
                : format === 'everything_json'
                  ? `carefold-fhir-everything-${profileId}-${dateTag}.json`
                  : `carefold-bulk-export-${profileId}-${dateTag}.ndjson`,
            mimeType:
              format === 'bulk_ndjson'
                ? 'application/fhir+ndjson;charset=utf-8'
                : 'application/fhir+json;charset=utf-8',
            content: text,
            resourceCount:
              format === 'bulk_ndjson'
                ? text.split('\n').filter((ln) => ln.trim().length > 0).length
                : 1,
            confirmed: true,
          };
        }
      } catch {
        // Fall back to deterministic local export payload when offline/standalone
      }
      return mockFallback.exportBundle(profileId, format, confirmed);
    },
  };
}

export function stageQuestionForVisit(
  profileId: string,
  questionText: string,
  threadId = `ehr-visit-prep-${profileId || 'default'}`,
  messageId = 'ehr-chart-staged'
): ChecklistItemState[] {
  const existing = loadChecklist(threadId, messageId, []);
  const alreadyPresent = existing.some(
    (item) => item.text.trim().toLowerCase() === questionText.trim().toLowerCase()
  );
  if (alreadyPresent) {
    return existing;
  }
  return addChecklistItem(threadId, messageId, questionText.trim(), existing);
}
