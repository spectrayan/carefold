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

export type EhrTerminologySystemLabel =
  | 'LOINC'
  | 'SNOMED CT'
  | 'RxNorm'
  | 'ICD-10-CM'
  | 'CVX'
  | 'CPT'
  | 'UCUM';

export interface EhrCodingBadge {
  systemLabel: EhrTerminologySystemLabel;
  systemUri: string;
  code: string;
  display: string;
  originalSystem?: string;
  wasNormalized?: boolean;
}

export interface EhrProvenanceMetadata {
  sourceName: string;
  recordedDate: string;
  sourceFormat: 'FHIR R4 Bundle' | 'C-CDA XML' | 'HL7v2 ORU/VXU/ADT' | 'SMART on FHIR v2' | 'Manual Entry';
  trustBoundary: 'verified_user' | 'external_untrusted';
  mergedPortals?: string[];
  versionId: string;
  lastUpdated: string;
}

export interface EhrResourceRevision {
  versionId: string;
  etag: string;
  operation: 'CREATE' | 'UPDATE' | 'MERGE';
  recordedAt: string;
  actorDisplay: string;
  sourceName: string;
  summary: string;
}

export interface EhrClinicalItemBase {
  id: string;
  resourceType:
    | 'Condition'
    | 'MedicationStatement'
    | 'MedicationRequest'
    | 'AllergyIntolerance'
    | 'Immunization'
    | 'Encounter'
    | 'Observation'
    | 'DiagnosticReport';
  title: string;
  subtitle?: string;
  codings: EhrCodingBadge[];
  provenance: EhrProvenanceMetadata;
  history: EhrResourceRevision[];
}

export interface EhrConditionItem extends EhrClinicalItemBase {
  resourceType: 'Condition';
  clinicalStatus: 'Active' | 'Resolved' | 'Inactive';
  verificationStatus: 'Confirmed' | 'Provisional';
  onsetDate: string;
  categoryDisplay: string;
}

export interface EhrMedicationItem extends EhrClinicalItemBase {
  resourceType: 'MedicationStatement' | 'MedicationRequest';
  status: 'Active' | 'Completed' | 'On Hold';
  dosageInstruction: string;
  routeDisplay?: string;
  prescriberDisplay?: string;
}

export interface EhrAllergyItem extends EhrClinicalItemBase {
  resourceType: 'AllergyIntolerance';
  criticality: 'High' | 'Low' | 'Unable to Assess';
  clinicalStatus: 'Active' | 'Inactive';
  reactionSummary: string;
  categoryDisplay: 'Medication' | 'Food' | 'Environment';
}

export interface EhrImmunizationItem extends EhrClinicalItemBase {
  resourceType: 'Immunization';
  status: 'Completed' | 'Not Done';
  administrationDate: string;
  lotNumber?: string;
  doseSeries?: string;
}

export interface EhrEncounterItem extends EhrClinicalItemBase {
  resourceType: 'Encounter';
  status: 'Planned' | 'Finished' | 'In Progress';
  encounterClass: 'Ambulatory' | 'Virtual' | 'Inpatient' | 'Emergency';
  periodStart: string;
  facilityDisplay: string;
  clinicianDisplay?: string;
  reasonDisplay: string;
}

export type EhrReferenceFlag = 'Normal' | 'High' | 'Low';

export interface EhrLabUnitVariant {
  value: number;
  unitDisplay: string;
  ucumCode: string;
  referenceRangeText: string;
  referenceLow?: number;
  referenceHigh?: number;
}

export interface EhrLabTrendPoint {
  date: string;
  canonicalValue: number;
  alternateValue?: number;
  flag: EhrReferenceFlag;
  sourceName: string;
}

export interface EhrLabObservationItem extends EhrClinicalItemBase {
  resourceType: 'Observation';
  panelId: string;
  panelTitle: string;
  panelLoincCode: string;
  categoryKey: 'metabolic' | 'lipids' | 'endocrine' | 'hematology';
  effectiveDate: string;
  flag: EhrReferenceFlag;
  canonicalMeasurement: EhrLabUnitVariant;
  alternateMeasurement?: EhrLabUnitVariant;
  trend: EhrLabTrendPoint[];
  suggestedVisitQuestion: string;
}

export interface EhrLabPanelGroup {
  panelId: string;
  panelTitle: string;
  panelLoincCode: string;
  categoryKey: 'metabolic' | 'lipids' | 'endocrine' | 'hematology';
  effectiveDate: string;
  provenance: EhrProvenanceMetadata;
  observations: EhrLabObservationItem[];
}

export interface EhrChartSnapshot {
  profileId: string;
  patientDisplayName: string;
  generatedAt: string;
  ipsCompositionLoinc: string;
  conditions: EhrConditionItem[];
  medications: EhrMedicationItem[];
  allergies: EhrAllergyItem[];
  immunizations: EhrImmunizationItem[];
  encounters: EhrEncounterItem[];
  labPanels: EhrLabPanelGroup[];
}

export type EhrExportFormat = 'ips_json' | 'everything_json' | 'bulk_ndjson';

export interface EhrExportResult {
  format: EhrExportFormat;
  filename: string;
  mimeType: string;
  content: string;
  resourceCount: number;
  confirmed: boolean;
}

export interface EhrChartDataSourceAdapter {
  readonly kind: 'fhir_r4_rest' | 'typed_mock';
  getChartSnapshot(profileId: string): Promise<EhrChartSnapshot>;
  getResourceHistory(
    profileId: string,
    resourceType: string,
    resourceId: string
  ): Promise<EhrResourceRevision[]>;
  exportBundle(
    profileId: string,
    format: EhrExportFormat,
    confirmed: boolean
  ): Promise<EhrExportResult>;
}
