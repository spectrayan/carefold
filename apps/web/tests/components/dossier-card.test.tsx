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

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  DossierCard,
  DOSSIER_PATIENT_DISCLAIMER,
  parseDossierPayload,
} from '@/components/chat/DossierCard';
import { VisitPrepCard } from '@/components/chat/VisitPrepCard';
import { InsuranceBenefitsCard } from '@/components/chat/InsuranceBenefitsCard';
import { GenericDossierCard } from '@/components/chat/GenericDossierCard';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import type { ToolTraceItem } from '@/components/ToolTraceCard';
import * as dossierExport from '@/lib/dossierExport';
import {
  saveChecklist,
  getChecklistKey,
} from '@/lib/checklistStorage';

describe('DossierCard & Typed Dossier Components (Issue #94)', () => {
  let downloadBlobSpy: any;
  let writeTextSpy: any;

  beforeEach(() => {
    downloadBlobSpy = vi.spyOn(dossierExport, 'downloadBlob').mockImplementation(() => {});
    writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
    if (typeof window !== 'undefined' && window.localStorage) {
      window.localStorage.clear();
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. VisitPrepCard Tests
  // =========================================================================
  describe('VisitPrepCard', () => {
    const mockVisitData = {
      reason_for_visit: 'Routine follow-up for chronic hypertension',
      physician_instructions: [
        'Continue taking Lisinopril 10mg daily',
        'Record morning blood pressure log',
        'Limit sodium intake to under 2,000mg per day',
      ],
      follow_up_timeline: '4 weeks',
      questions_to_ask: [
        'What should my systolic target be during morning readings?',
        'Should I repeat the basic metabolic panel before next visit?',
      ],
    };

    it('renders visit reason, instructions, follow-up timeline badge, and mandatory disclaimer', () => {
      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId="thread-test-1"
          messageId="msg-1"
          agentTitle="Cardiology Guide"
          isGrounded={true}
        />
      );

      // Header & Agent
      expect(screen.getByText('Visit Preparation Dossier')).toBeInTheDocument();
      expect(screen.getByText('Prepared with Cardiology Guide')).toBeInTheDocument();

      // Grounding badge
      expect(screen.getByTestId('dossier-grounded-badge')).toHaveTextContent('Grounded');

      // Follow-up timeline badge
      const timelineBadge = screen.getByTestId('visit-followup-badge');
      expect(timelineBadge).toHaveTextContent('Follow-up: 4 weeks');

      // Reason for visit
      expect(screen.getByTestId('visit-reason')).toHaveTextContent(
        'Routine follow-up for chronic hypertension'
      );

      // Physician instructions
      const instructions = screen.getByTestId('visit-instructions');
      expect(instructions).toHaveTextContent('Continue taking Lisinopril 10mg daily');
      expect(instructions).toHaveTextContent('Record morning blood pressure log');

      // Mandatory non-clinical disclaimer banner
      const disclaimer = screen.getByTestId('dossier-disclaimer-banner');
      expect(disclaimer).toHaveTextContent(DOSSIER_PATIENT_DISCLAIMER);
      expect(disclaimer).toHaveTextContent(
        'Extracted from your document. Check details with your care team or insurer.'
      );
    });

    it('contains zero diagnostic language across all rendered text', () => {
      const { container } = render(
        <VisitPrepCard
          data={mockVisitData}
          threadId="thread-test-1"
          messageId="msg-1"
        />
      );

      const allText = container.textContent || '';
      // Ensure zero diagnostic or prescriptive words
      expect(allText.toLowerCase()).not.toContain('we diagnose');
      expect(allText.toLowerCase()).not.toContain('formal diagnosis');
      expect(allText.toLowerCase()).not.toContain('prescribed by ai');
    });

    it('handles interactive checklist checkbox toggling and localStorage persistence', () => {
      const threadId = 'thread-visit-checklist';
      const messageId = 'msg-visit-1';

      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId={threadId}
          messageId={messageId}
        />
      );

      const firstQuestion = screen.getByText(
        'What should my systolic target be during morning readings?'
      );
      expect(firstQuestion).not.toHaveClass('line-through');

      // Checkbox button for first question
      const checkboxes = screen.getAllByRole('button', { name: /Mark .* as completed/i });
      expect(checkboxes.length).toBe(2);

      // Click first checkbox
      fireEvent.click(checkboxes[0]);
      expect(firstQuestion).toHaveClass('line-through');

      // Verify localStorage was updated
      const storageKey = getChecklistKey(threadId, messageId);
      const storedRaw = window.localStorage.getItem(storageKey);
      expect(storedRaw).toBeTruthy();
      const parsed = JSON.parse(storedRaw!);
      expect(parsed[0].completed).toBe(true);
      expect(parsed[1].completed).toBe(false);

      // Toggle again to uncheck
      const uncheckButtons = screen.getAllByRole('button', { name: /Mark .* as incomplete/i });
      fireEvent.click(uncheckButtons[0]);
      expect(firstQuestion).not.toHaveClass('line-through');
    });

    it('allows adding custom questions to the checklist and persists them', () => {
      const threadId = 'thread-add-q';
      const messageId = 'msg-add-1';

      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId={threadId}
          messageId={messageId}
        />
      );

      const input = screen.getByTestId('add-question-input');
      const addBtn = screen.getByTestId('add-question-btn');

      fireEvent.change(input, { target: { value: 'Can I exercise before taking blood pressure?' } });
      fireEvent.click(addBtn);

      expect(
        screen.getByText('Can I exercise before taking blood pressure?')
      ).toBeInTheDocument();

      // Verify persistence
      const storageKey = getChecklistKey(threadId, messageId);
      const parsed = JSON.parse(window.localStorage.getItem(storageKey)!);
      expect(parsed.length).toBe(3);
      expect(parsed[2].text).toBe('Can I exercise before taking blood pressure?');
      expect(parsed[2].isCustom).toBe(true);
    });

    it('rehydrates saved checklist state from localStorage on mount', () => {
      const threadId = 'thread-rehydrate';
      const messageId = 'msg-rehydrate-1';

      // Pre-populate localStorage
      saveChecklist(threadId, messageId, [
        { id: 'q-1', text: 'Pre-saved question 1', completed: true },
        { id: 'q-2', text: 'Pre-saved question 2', completed: false },
      ]);

      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId={threadId}
          messageId={messageId}
        />
      );

      expect(screen.getByText('Pre-saved question 1')).toHaveClass('line-through');
      expect(screen.getByText('Pre-saved question 2')).not.toHaveClass('line-through');
    });

    it('copies formatted Markdown to clipboard with visual feedback', async () => {
      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId="thread-copy"
          messageId="msg-copy-1"
        />
      );

      const copyBtn = screen.getByTestId('dossier-copy-btn');
      fireEvent.click(copyBtn);

      await waitFor(() => {
        expect(writeTextSpy).toHaveBeenCalledTimes(1);
      });

      const copiedContent = writeTextSpy.mock.calls[0][0];
      expect(copiedContent).toContain('# Clinical Visit Preparation Dossier');
      expect(copiedContent).toContain(DOSSIER_PATIENT_DISCLAIMER);
      expect(copiedContent).toContain('Routine follow-up for chronic hypertension');
      expect(copiedContent).toContain('Continue taking Lisinopril 10mg daily');
      expect(copiedContent).toContain('- [ ] What should my systolic target be');

      expect(screen.getByText('Copied!')).toBeInTheDocument();
    });

    it('exports formatted Markdown file via downloadBlob', () => {
      render(
        <VisitPrepCard
          data={mockVisitData}
          threadId="thread-export"
          messageId="msg-export-1"
        />
      );

      const exportBtn = screen.getByTestId('dossier-export-btn');
      fireEvent.click(exportBtn);

      expect(downloadBlobSpy).toHaveBeenCalledTimes(1);
      const [blob, filename] = downloadBlobSpy.mock.calls[0];
      expect(blob).toBeInstanceOf(Blob);
      expect(filename).toMatch(/^carefold-visit-prep-\d{4}-\d{2}-\d{2}\.md$/);
    });
  });

  // =========================================================================
  // 2. InsuranceBenefitsCard Tests
  // =========================================================================
  describe('InsuranceBenefitsCard', () => {
    const mockInsuranceData = {
      deductible: '$1,500',
      copays: {
        primary_care: '$25',
        specialist: '$50',
        urgent_care: '$75',
        emergency_room: '$250',
      },
      coinsurance: '20%',
      out_of_pocket_maximum: '$6,000',
      in_out_network_rules:
        'In-network preventative care covered at 100%. Out-of-network services subject to 40% coinsurance after separate $3,000 deductible.',
      prior_authorization_flags: ['Advanced MRI Imaging', 'Non-formulary Biologics'],
    };

    it('renders financial metrics, copays table, network rules, and prior auth badges', () => {
      render(
        <InsuranceBenefitsCard
          data={mockInsuranceData}
          agentTitle="Benefits Guide"
          isGrounded={true}
        />
      );

      expect(screen.getByText('Insurance Benefits Summary')).toBeInTheDocument();
      expect(screen.getByText('Prepared with Benefits Guide')).toBeInTheDocument();
      expect(screen.getByTestId('dossier-grounded-badge')).toHaveTextContent('Grounded');

      // Top metrics
      expect(screen.getByTestId('metric-deductible')).toHaveTextContent('$1,500');
      expect(screen.getByTestId('metric-oop-max')).toHaveTextContent('$6,000');
      expect(screen.getByTestId('metric-coinsurance')).toHaveTextContent('20%');

      // Copays table
      const copaysTable = screen.getByTestId('copays-table');
      expect(copaysTable).toHaveTextContent('Primary Care');
      expect(copaysTable).toHaveTextContent('$25');
      expect(copaysTable).toHaveTextContent('Specialist');
      expect(copaysTable).toHaveTextContent('$50');
      expect(copaysTable).toHaveTextContent('Emergency Room');
      expect(copaysTable).toHaveTextContent('$250');

      // Network rules
      expect(screen.getByTestId('network-rules')).toHaveTextContent(
        'In-network preventative care covered at 100%'
      );

      // Prior auth flags
      const priorAuth = screen.getByTestId('prior-auth-flags');
      expect(priorAuth).toHaveTextContent('Advanced MRI Imaging');
      expect(priorAuth).toHaveTextContent('Non-formulary Biologics');

      // Disclaimer
      expect(screen.getByTestId('dossier-disclaimer-banner')).toHaveTextContent(
        DOSSIER_PATIENT_DISCLAIMER
      );
    });

    it('handles empty copays gracefully without rendering broken table', () => {
      render(
        <InsuranceBenefitsCard
          data={{
            ...mockInsuranceData,
            copays: {},
          }}
        />
      );

      expect(screen.queryByTestId('copays-table')).not.toBeInTheDocument();
      expect(
        screen.getByText('No fixed copays specified in document.')
      ).toBeInTheDocument();
    });

    it('copies and exports insurance benefits markdown', async () => {
      render(<InsuranceBenefitsCard data={mockInsuranceData} />);

      // Copy
      fireEvent.click(screen.getByTestId('dossier-copy-btn'));
      await waitFor(() => {
        expect(writeTextSpy).toHaveBeenCalledTimes(1);
      });
      const copied = writeTextSpy.mock.calls[0][0];
      expect(copied).toContain('# Health Insurance Benefits Dossier');
      expect(copied).toContain('Annual Deductible:** $1,500');
      expect(copied).toContain('| Primary Care | $25 |');

      // Export
      fireEvent.click(screen.getByTestId('dossier-export-btn'));
      expect(downloadBlobSpy).toHaveBeenCalledTimes(1);
      const [blob, filename] = downloadBlobSpy.mock.calls[0];
      expect(blob).toBeInstanceOf(Blob);
      expect(filename).toMatch(/^carefold-insurance-benefits-\d{4}-\d{2}-\d{2}\.md$/);
    });
  });

  // =========================================================================
  // 3. GenericDossierCard Tests
  // =========================================================================
  describe('GenericDossierCard', () => {
    const mockGenericData = {
      summary: 'Outpatient discharge instructions following minor orthopedic arthroscopy.',
      key_numerical_values: {
        recovery_days: '5 to 7 days',
        ice_protocol_minutes: '20 minutes every 2 hours',
        weight_bearing_percentage: '50% as tolerated',
      },
      sections: ['Discharge Instructions', 'Wound Dressing', 'Emergency Contact'],
    };

    it('renders executive summary, key metrics grid, sections list, and disclaimer', () => {
      render(
        <GenericDossierCard
          data={mockGenericData}
          agentTitle="Records Coordinator"
          isGrounded={true}
        />
      );

      expect(screen.getByText('Document Summary Dossier')).toBeInTheDocument();
      expect(screen.getByText('Prepared with Records Coordinator')).toBeInTheDocument();
      expect(screen.getByTestId('dossier-grounded-badge')).toHaveTextContent('Grounded');

      // Executive summary
      expect(screen.getByTestId('generic-summary')).toHaveTextContent(
        'Outpatient discharge instructions following minor orthopedic arthroscopy.'
      );

      // Key metrics grid
      const keyValues = screen.getByTestId('generic-key-values');
      expect(keyValues).toHaveTextContent('Recovery Days');
      expect(keyValues).toHaveTextContent('5 to 7 days');
      expect(keyValues).toHaveTextContent('Ice Protocol Minutes');
      expect(keyValues).toHaveTextContent('20 minutes every 2 hours');

      // Sections
      const sections = screen.getByTestId('generic-sections');
      expect(sections).toHaveTextContent('Discharge Instructions');
      expect(sections).toHaveTextContent('Wound Dressing');
      expect(sections).toHaveTextContent('Emergency Contact');

      // Disclaimer
      expect(screen.getByTestId('dossier-disclaimer-banner')).toHaveTextContent(
        DOSSIER_PATIENT_DISCLAIMER
      );
    });

    it('copies and exports generic document markdown', async () => {
      render(<GenericDossierCard data={mockGenericData} />);

      // Copy
      fireEvent.click(screen.getByTestId('dossier-copy-btn'));
      await waitFor(() => {
        expect(writeTextSpy).toHaveBeenCalledTimes(1);
      });
      const copied = writeTextSpy.mock.calls[0][0];
      expect(copied).toContain('# Document Extraction Summary');
      expect(copied).toContain('Outpatient discharge instructions');
      expect(copied).toContain('Recovery Days:** 5 to 7 days');

      // Export
      fireEvent.click(screen.getByTestId('dossier-export-btn'));
      expect(downloadBlobSpy).toHaveBeenCalledTimes(1);
      const [blob, filename] = downloadBlobSpy.mock.calls[0];
      expect(blob).toBeInstanceOf(Blob);
      expect(filename).toMatch(/^carefold-document-summary-\d{4}-\d{2}-\d{2}\.md$/);
    });
  });

  // =========================================================================
  // 4. DossierCard Router & Parser Tests
  // =========================================================================
  describe('DossierCard & parseDossierPayload', () => {
    it('routes clinical_visit tool trace to VisitPrepCard', () => {
      const trace: ToolTraceItem = {
        id: 't-visit',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: {
          status: 'success',
          dossier_type: 'clinical_visit',
          dossier: {
            reason_for_visit: 'Hypertension checkup',
            physician_instructions: ['Take medication'],
            follow_up_timeline: '2 weeks',
            questions_to_ask: ['What is my target?'],
          },
          is_grounded: true,
        },
      };

      render(
        <DossierCard
          trace={trace}
          threadId="th-1"
          messageId="m-1"
          agentTitle="Cardiology Guide"
        />
      );

      expect(screen.getByTestId('visit-prep-card')).toBeInTheDocument();
      expect(screen.getByText('Hypertension checkup')).toBeInTheDocument();
    });

    it('routes insurance_benefits tool trace to InsuranceBenefitsCard', () => {
      const trace: ToolTraceItem = {
        id: 't-ins',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: {
          status: 'success',
          dossier_type: 'insurance_benefits',
          dossier: {
            deductible: '$2,000',
            copays: { specialist: '$40' },
            coinsurance: '15%',
            out_of_pocket_maximum: '$5,000',
          },
          is_grounded: true,
        },
      };

      render(<DossierCard trace={trace} agentTitle="Benefits Guide" />);
      expect(screen.getByTestId('insurance-benefits-card')).toBeInTheDocument();
      expect(screen.getByTestId('metric-deductible')).toHaveTextContent('$2,000');
    });

    it('routes generic_document tool trace to GenericDossierCard', () => {
      const trace: ToolTraceItem = {
        id: 't-gen',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: {
          status: 'success',
          dossier_type: 'generic_document',
          dossier: {
            summary: 'General medical history overview',
            key_numerical_values: { blood_type: 'O Positive' },
            sections: ['History', 'Allergies'],
          },
          is_grounded: true,
        },
      };

      render(<DossierCard trace={trace} agentTitle="Records Coordinator" />);
      expect(screen.getByTestId('generic-dossier-card')).toBeInTheDocument();
      expect(screen.getByText('General medical history overview')).toBeInTheDocument();
    });

    it('correctly parses JSON stringified output in tool trace', () => {
      const trace: ToolTraceItem = {
        id: 't-json-str',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: JSON.stringify({
          status: 'success',
          dossier_type: 'clinical_visit',
          dossier: {
            reason_for_visit: 'Ear infection check',
            physician_instructions: ['Amoxicillin for 10 days'],
          },
        }),
      };

      render(<DossierCard trace={trace} />);
      expect(screen.getByTestId('visit-prep-card')).toBeInTheDocument();
      expect(screen.getByText('Ear infection check')).toBeInTheDocument();
    });

    it('safely falls back (returns null) on malformed JSON string without crashing', () => {
      const trace: ToolTraceItem = {
        id: 't-malformed',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: '{this is not valid json!@@#',
      };

      const result = parseDossierPayload(trace);
      expect(result).toBeNull();

      const { container } = render(<DossierCard trace={trace} />);
      expect(container.firstChild).toBeNull();
    });

    it('safely falls back (returns null) on unknown or corrupt dossier schema', () => {
      const trace: ToolTraceItem = {
        id: 't-unknown',
        tool: 'extract_document_dossier',
        status: 'completed',
        output: {
          status: 'success',
          dossier_type: 'unrecognized_custom_v3',
          dossier: { foo: 'bar', baz: 123 },
        },
      };

      const result = parseDossierPayload(trace);
      expect(result).toBeNull();

      const { container } = render(<DossierCard trace={trace} />);
      expect(container.firstChild).toBeNull();
    });

    it('safely falls back (returns null) on null, undefined, or primitive output', () => {
      expect(parseDossierPayload({ tool: 'extract_document_dossier', status: 'completed', output: null } as any)).toBeNull();
      expect(parseDossierPayload({ tool: 'extract_document_dossier', status: 'completed', output: undefined } as any)).toBeNull();
      expect(parseDossierPayload({ tool: 'extract_document_dossier', status: 'completed', output: 12345 } as any)).toBeNull();
      expect(parseDossierPayload({ tool: 'extract_document_dossier', status: 'completed', output: true } as any)).toBeNull();
    });

    it('returns null when tool is still running (not completed)', () => {
      const trace: ToolTraceItem = {
        id: 't-running',
        tool: 'extract_document_dossier',
        status: 'running',
        output: {
          dossier_type: 'clinical_visit',
          dossier: { reason_for_visit: 'Checkup' },
        },
      };

      expect(parseDossierPayload(trace)).toBeNull();
      const { container } = render(<DossierCard trace={trace} />);
      expect(container.firstChild).toBeNull();
    });

    it('returns null when tool is not extract_document_dossier', () => {
      const trace: ToolTraceItem = {
        id: 't-other',
        tool: 'attach-read',
        status: 'completed',
        output: { text: 'Document content' },
      };

      expect(parseDossierPayload(trace)).toBeNull();
      const { container } = render(<DossierCard trace={trace} />);
      expect(container.firstChild).toBeNull();
    });
  });

  // =========================================================================
  // 5. ChatMessageItem Integration Tests
  // =========================================================================
  describe('ChatMessageItem Integration with DossierCard', () => {
    it('renders DossierCard below message while preserving raw ToolTraceCard in embedded-tool-traces', () => {
      const message: ChatMessage = {
        id: 'msg-extract-1',
        role: 'assistant',
        content: 'I analyzed your clinical visit document. Here is your preparation summary.',
        toolTraces: [
          {
            id: 'trace-doc-1',
            tool: 'extract_document_dossier',
            status: 'completed',
            duration_ms: 120,
            output: {
              status: 'success',
              dossier_type: 'clinical_visit',
              dossier: {
                reason_for_visit: 'Annual physical exam',
                physician_instructions: ['Schedule fasting lipid panel'],
                follow_up_timeline: '1 year',
                questions_to_ask: ['Are my immunizations up to date?'],
              },
              is_grounded: true,
            },
          },
        ],
      };

      render(<ChatMessageItem message={message} threadId="th-integrated" />);

      // 1. ToolTraceCard is present in embedded-tool-traces
      const toolTraces = screen.getByTestId('embedded-tool-traces');
      expect(toolTraces).toHaveTextContent('extract_document_dossier');
      expect(toolTraces).toHaveTextContent('Completed');

      // 2. Message content is rendered
      expect(screen.getByText(/I analyzed your clinical visit document/i)).toBeInTheDocument();

      // 3. DossierCard is rendered below message
      expect(screen.getByTestId('chat-message-dossiers')).toBeInTheDocument();
      expect(screen.getByTestId('visit-prep-card')).toBeInTheDocument();
      expect(screen.getByText('Annual physical exam')).toBeInTheDocument();

      // 4. Raw JSON trace remains accessible in ToolTraceCard
      const traceToggleBtn = screen.getByRole('button', { name: /extract_document_dossier/i });
      fireEvent.click(traceToggleBtn);
      const traceOutput = screen.getByTestId('tool-trace-output');
      expect(traceOutput).toHaveTextContent('"dossier_type": "clinical_visit"');
    });

    it('does not crash ChatMessageItem when tool trace output is malformed', () => {
      const message: ChatMessage = {
        id: 'msg-corrupt-1',
        role: 'assistant',
        content: 'Extraction completed with unexpected structure.',
        toolTraces: [
          {
            id: 'trace-corrupt-1',
            tool: 'extract_document_dossier',
            status: 'completed',
            output: 'corrupt-string-that-is-not-json',
          },
        ],
      };

      render(<ChatMessageItem message={message} />);

      // Assistant message renders cleanly
      expect(screen.getByTestId('chat-message-assistant')).toBeInTheDocument();
      expect(screen.getByText('Extraction completed with unexpected structure.')).toBeInTheDocument();

      // Tool trace is visible
      expect(screen.getByTestId('embedded-tool-traces')).toHaveTextContent('extract_document_dossier');

      // Dossier card is not rendered (returned null safely)
      expect(screen.queryByTestId('visit-prep-card')).not.toBeInTheDocument();
      expect(screen.queryByTestId('insurance-benefits-card')).not.toBeInTheDocument();
      expect(screen.queryByTestId('generic-dossier-card')).not.toBeInTheDocument();
    });
  });
});
