/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

'use client';

import React from 'react';
import type { ToolTraceItem } from '../ToolTraceCard';
import type {
  ClinicalVisitDossierData,
  InsuranceBenefitsDossierData,
  GenericDocumentDossierData,
} from '@/lib/types';
import { VisitPrepCard, DOSSIER_PATIENT_DISCLAIMER } from './VisitPrepCard';
import { InsuranceBenefitsCard } from './InsuranceBenefitsCard';
import { GenericDossierCard } from './GenericDossierCard';

export { DOSSIER_PATIENT_DISCLAIMER };

export interface DossierCardProps {
  trace: ToolTraceItem;
  threadId?: string;
  messageId?: string;
  agentTitle?: string;
}

export type ParsedDossierResult =
  | { type: 'clinical_visit'; data: ClinicalVisitDossierData; isGrounded?: boolean }
  | { type: 'insurance_benefits'; data: InsuranceBenefitsDossierData; isGrounded?: boolean }
  | { type: 'generic_document'; data: GenericDocumentDossierData; isGrounded?: boolean };

/**
 * Safely parses the output or result of an extract_document_dossier tool trace.
 * Returns null if the trace is not completed, output is missing or malformed,
 * or if the schema is unrecognized.
 */
export function parseDossierPayload(trace: ToolTraceItem): ParsedDossierResult | null {
  try {
    if (!trace || trace.tool !== 'extract_document_dossier') {
      return null;
    }

    if (trace.status !== 'completed') {
      return null;
    }

    let payload = trace.result ?? trace.output;
    if (payload === undefined || payload === null) {
      return null;
    }

    if (typeof payload === 'string') {
      try {
        payload = JSON.parse(payload);
      } catch {
        return null;
      }
    }

    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
      return null;
    }

    const declaredType =
      typeof payload.dossier_type === 'string'
        ? payload.dossier_type.trim().toLowerCase()
        : '';

    const rawDossier =
      payload.dossier && typeof payload.dossier === 'object' && !Array.isArray(payload.dossier)
        ? payload.dossier
        : payload;

    const isGrounded =
      typeof payload.is_grounded === 'boolean' ? payload.is_grounded : true;

    // Route by declared dossier_type
    if (declaredType === 'clinical_visit' || declaredType === 'clinical') {
      const hasClinicalFields =
        rawDossier.reason_for_visit !== undefined ||
        Array.isArray(rawDossier.physician_instructions) ||
        rawDossier.follow_up_timeline !== undefined ||
        Array.isArray(rawDossier.questions_to_ask);

      if (hasClinicalFields) {
        return {
          type: 'clinical_visit',
          data: rawDossier as ClinicalVisitDossierData,
          isGrounded,
        };
      }
      return null;
    }

    if (declaredType === 'insurance_benefits' || declaredType === 'insurance') {
      const hasInsuranceFields =
        rawDossier.deductible !== undefined ||
        (rawDossier.copays && typeof rawDossier.copays === 'object') ||
        rawDossier.coinsurance !== undefined ||
        rawDossier.out_of_pocket_maximum !== undefined ||
        rawDossier.in_out_network_rules !== undefined ||
        Array.isArray(rawDossier.prior_authorization_flags);

      if (hasInsuranceFields) {
        return {
          type: 'insurance_benefits',
          data: rawDossier as InsuranceBenefitsDossierData,
          isGrounded,
        };
      }
      return null;
    }

    if (declaredType === 'generic_document' || declaredType === 'generic') {
      const hasGenericFields =
        rawDossier.summary !== undefined ||
        (rawDossier.key_numerical_values && typeof rawDossier.key_numerical_values === 'object') ||
        Array.isArray(rawDossier.sections);

      if (hasGenericFields) {
        return {
          type: 'generic_document',
          data: rawDossier as GenericDocumentDossierData,
          isGrounded,
        };
      }
      return null;
    }

    // If no declaredType or unknown declaredType: infer from keys if unambiguous,
    // otherwise if declaredType is explicitly unknown (e.g. "unrecognized"), return null
    if (declaredType && !['clinical_visit', 'clinical', 'insurance_benefits', 'insurance', 'generic_document', 'generic'].includes(declaredType)) {
      return null;
    }

    // Implicit key detection
    if (
      rawDossier.reason_for_visit !== undefined ||
      Array.isArray(rawDossier.physician_instructions) ||
      Array.isArray(rawDossier.questions_to_ask)
    ) {
      return {
        type: 'clinical_visit',
        data: rawDossier as ClinicalVisitDossierData,
        isGrounded,
      };
    }

    if (
      rawDossier.deductible !== undefined ||
      (rawDossier.copays && typeof rawDossier.copays === 'object') ||
      rawDossier.out_of_pocket_maximum !== undefined ||
      Array.isArray(rawDossier.prior_authorization_flags)
    ) {
      return {
        type: 'insurance_benefits',
        data: rawDossier as InsuranceBenefitsDossierData,
        isGrounded,
      };
    }

    if (
      rawDossier.summary !== undefined ||
      (rawDossier.key_numerical_values && typeof rawDossier.key_numerical_values === 'object') ||
      Array.isArray(rawDossier.sections)
    ) {
      return {
        type: 'generic_document',
        data: rawDossier as GenericDocumentDossierData,
        isGrounded,
      };
    }

    return null;
  } catch {
    return null;
  }
}

/**
 * Container component that parses extract_document_dossier tool results and routes
 * to the appropriate typed card (VisitPrepCard, InsuranceBenefitsCard, GenericDossierCard).
 * Returns null on malformed or unknown payloads to safely preserve raw JSON tool traces.
 */
export function DossierCard({
  trace,
  threadId,
  messageId,
  agentTitle,
}: DossierCardProps) {
  const parsed = parseDossierPayload(trace);
  if (!parsed) {
    return null;
  }

  if (parsed.type === 'clinical_visit') {
    return (
      <VisitPrepCard
        data={parsed.data}
        threadId={threadId}
        messageId={messageId}
        agentTitle={agentTitle}
        isGrounded={parsed.isGrounded}
      />
    );
  }

  if (parsed.type === 'insurance_benefits') {
    return (
      <InsuranceBenefitsCard
        data={parsed.data}
        agentTitle={agentTitle}
        isGrounded={parsed.isGrounded}
      />
    );
  }

  if (parsed.type === 'generic_document') {
    return (
      <GenericDossierCard
        data={parsed.data}
        agentTitle={agentTitle}
        isGrounded={parsed.isGrounded}
      />
    );
  }

  return null;
}
