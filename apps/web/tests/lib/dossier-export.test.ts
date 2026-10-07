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

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  generateDossierFilename,
  formatDossierMarkdown,
  formatDossierJson,
  downloadBlob,
  exportDossier,
  NON_CLINICAL_DISCLAIMER_TEXT,
  type DossierExportOptions,
} from '@/lib/dossierExport';
import type { ChatMessage } from '@/lib/types';
import type { AgentSummary } from '@/types/api';

describe('Dossier Export Utilities (apps/web/src/lib/dossierExport.ts)', () => {
  const mockAgent: AgentSummary = {
    id: 'cardiology-guide',
    title: 'Cardiology Guide',
    version: '0.4.0',
    risk_class: 'clinical_assist',
    skills: ['cardiology-prep', 'emergency-red-flags'],
    effectiveTools: ['attach-read', 'workspace-note'],
    starters: ['Help me prepare for my cardiology appointment.'],
    description: 'Pre-visit cardiology preparation and cardiovascular wellness steward.',
  };

  const sampleMessages: ChatMessage[] = [
    {
      id: 'msg-1',
      role: 'user',
      content: 'I have an upcoming appointment with a cardiologist about mild palpitations.',
      timestamp: '2026-10-07T04:00:00.000Z',
    },
    {
      id: 'msg-2',
      role: 'assistant',
      content:
        'To make the most of your cardiology appointment, here is a checklist of questions and symptom tracking recommendations.',
      timestamp: '2026-10-07T04:01:00.000Z',
      toolTraces: [
        {
          tool: 'extract_document_dossier',
          status: 'completed',
          input: { file: 'secret_records.pdf' },
          output: 'Internal clinical extraction payload',
        },
      ],
      traces: [
        {
          tool: 'workspace-note',
          status: 'completed',
          input: { note: 'internal trace note' },
          output: 'ok',
        },
      ],
      attachments: ['attachment_binary_buffer_data_12345'],
    },
  ];

  describe('generateDossierFilename', () => {
    it('generates markdown filename adhering to carefold-<agent-id>-prep-<YYYY-MM-DD>.md pattern', () => {
      const fixedDate = new Date('2026-10-07T12:00:00Z');
      const filename = generateDossierFilename('cardiology-guide', 'md', fixedDate);
      expect(filename).toBe('carefold-cardiology-guide-prep-2026-10-07.md');
    });

    it('generates json filename adhering to carefold-<agent-id>-prep-<YYYY-MM-DD>.json pattern', () => {
      const fixedDate = new Date('2026-10-07T12:00:00Z');
      const filename = generateDossierFilename('claims-appeals-guide', 'json', fixedDate);
      expect(filename).toBe('carefold-claims-appeals-guide-prep-2026-10-07.json');
    });

    it('sanitizes special characters, whitespace, and uppercase in agent ID', () => {
      const fixedDate = new Date('2026-10-07T12:00:00Z');
      const filename = generateDossierFilename('Cardiology Guide / Specialist!', 'md', fixedDate);
      expect(filename).toBe('carefold-cardiology-guide-specialist-prep-2026-10-07.md');
    });

    it('falls back to "general" if agentId is missing or empty', () => {
      const fixedDate = new Date('2026-10-07T12:00:00Z');
      const filename = generateDossierFilename('', 'md', fixedDate);
      expect(filename).toBe('carefold-general-prep-2026-10-07.md');
    });
  });

  describe('formatDossierMarkdown', () => {
    it('creates valid Markdown with title and prominent non-clinical disclaimer banner blockquote', () => {
      const md = formatDossierMarkdown({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
        threadId: 'thread-cardiology-123',
        exportedAt: '2026-10-07T04:15:00.000Z',
      });

      expect(md).toContain('# Carefold Consultation Dossier — Cardiology Guide');
      expect(md).toContain('> **NON-CLINICAL SAFETY DISCLAIMER**:');
      expect(md).toContain(NON_CLINICAL_DISCLAIMER_TEXT);
    });

    it('includes metadata header with Agent ID, Risk Class, Thread ID, and turn counts', () => {
      const md = formatDossierMarkdown({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
        threadId: 'thread-cardiology-123',
        exportedAt: '2026-10-07T04:15:00.000Z',
      });

      expect(md).toContain('**Agent**: Cardiology Guide (`cardiology-guide`)');
      expect(md).toContain('**Risk Class**: clinical_assist');
      expect(md).toContain('**Exported**: 2026-10-07T04:15:00.000Z');
      expect(md).toContain('**Thread ID**: `thread-cardiology-123`');
      expect(md).toContain('**Total Messages**: 2');
    });

    it('formats conversation turns with patient and agent headers while preserving message body', () => {
      const md = formatDossierMarkdown({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
      });

      expect(md).toContain('### Patient (User)');
      expect(md).toContain('I have an upcoming appointment with a cardiologist about mild palpitations.');
      expect(md).toContain('### Cardiology Guide (Assistant)');
      expect(md).toContain('To make the most of your cardiology appointment, here is a checklist');
    });

    it('strictly excludes raw tool traces and attachment binary buffers to protect privacy', () => {
      const md = formatDossierMarkdown({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
      });

      expect(md).not.toContain('extract_document_dossier');
      expect(md).not.toContain('secret_records.pdf');
      expect(md).not.toContain('Internal clinical extraction payload');
      expect(md).not.toContain('attachment_binary_buffer_data_12345');
      expect(md).not.toContain('internal trace note');
    });

    it('handles empty message list and missing agent gracefully', () => {
      const md = formatDossierMarkdown({
        agent: null,
        agentId: 'visit-steward',
        messages: [],
      });

      expect(md).toContain('# Carefold Consultation Dossier — Health Assistant');
      expect(md).toContain('No consultation messages recorded.');
    });
  });

  describe('formatDossierJson', () => {
    it('produces valid JSON with schema version 1.0, ISO exportedAt, disclaimer, and session metadata', () => {
      const jsonStr = formatDossierJson({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
        threadId: 'thread-cardiology-123',
        exportedAt: '2026-10-07T04:15:00.000Z',
      });

      const parsed = JSON.parse(jsonStr);
      expect(parsed.schema_version).toBe('1.0');
      expect(parsed.schemaVersion).toBe('1.0');
      expect(parsed.exportedAt).toBe('2026-10-07T04:15:00.000Z');
      expect(parsed.disclaimer).toBe(NON_CLINICAL_DISCLAIMER_TEXT);
      expect(parsed.session).toEqual({
        agentId: 'cardiology-guide',
        agentTitle: 'Cardiology Guide',
        riskClass: 'clinical_assist',
        threadId: 'thread-cardiology-123',
      });
      expect(parsed.summary).toEqual({
        totalMessages: 2,
        userTurns: 1,
        assistantTurns: 1,
      });
    });

    it('sanitizes message array and excludes tool traces and attachment payloads', () => {
      const jsonStr = formatDossierJson({
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
      });

      const parsed = JSON.parse(jsonStr);
      expect(parsed.messages).toHaveLength(2);

      const assistantMsg = parsed.messages[1];
      expect(assistantMsg.id).toBe('msg-2');
      expect(assistantMsg.role).toBe('assistant');
      expect(assistantMsg.content).toContain('To make the most of your cardiology appointment');

      // Privacy checks: no tool traces or attachments leaked
      expect(assistantMsg.toolTraces).toBeUndefined();
      expect(assistantMsg.traces).toBeUndefined();
      expect(assistantMsg.attachments).toBeUndefined();
      expect(jsonStr).not.toContain('secret_records.pdf');
      expect(jsonStr).not.toContain('attachment_binary_buffer_data_12345');
    });

    it('handles empty messages array with zero turn counts', () => {
      const jsonStr = formatDossierJson({
        agent: null,
        agentId: 'general',
        messages: [],
      });

      const parsed = JSON.parse(jsonStr);
      expect(parsed.messages).toEqual([]);
      expect(parsed.summary.totalMessages).toBe(0);
      expect(parsed.summary.userTurns).toBe(0);
      expect(parsed.summary.assistantTurns).toBe(0);
    });
  });

  describe('downloadBlob and exportDossier', () => {
    let createdUrls: string[] = [];
    let revokedUrls: string[] = [];
    let clickedAnchors: HTMLAnchorElement[] = [];

    beforeEach(() => {
      createdUrls = [];
      revokedUrls = [];
      clickedAnchors = [];

      vi.spyOn(window.URL, 'createObjectURL').mockImplementation(() => {
        const url = `blob:test-${Math.random().toString(36).substring(2, 9)}`;
        createdUrls.push(url);
        return url;
      });

      vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation((url: string) => {
        revokedUrls.push(url);
      });

      vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
        clickedAnchors.push(this);
      });
    });

    it('downloadBlob creates anchor, sets download filename, triggers click, and revokes object URL', () => {
      const blob = new Blob(['# Test Markdown'], { type: 'text/markdown;charset=utf-8' });
      downloadBlob(blob, 'carefold-test.md');

      expect(createdUrls).toHaveLength(1);
      expect(clickedAnchors).toHaveLength(1);
      expect(clickedAnchors[0].download).toBe('carefold-test.md');
      expect(revokedUrls).toHaveLength(1);
      expect(revokedUrls[0]).toBe(createdUrls[0]);
    });

    it('exportDossier exports markdown file end-to-end', () => {
      const options: DossierExportOptions = {
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
        threadId: 'thread-cardiology-123',
      };

      exportDossier('md', options);

      expect(createdUrls).toHaveLength(1);
      expect(clickedAnchors).toHaveLength(1);
      expect(clickedAnchors[0].download).toMatch(/^carefold-cardiology-guide-prep-\d{4}-\d{2}-\d{2}\.md$/);
      expect(revokedUrls).toHaveLength(1);
    });

    it('exportDossier exports json file end-to-end', () => {
      const options: DossierExportOptions = {
        agent: mockAgent,
        agentId: 'cardiology-guide',
        messages: sampleMessages,
        threadId: 'thread-cardiology-123',
      };

      exportDossier('json', options);

      expect(createdUrls).toHaveLength(1);
      expect(clickedAnchors).toHaveLength(1);
      expect(clickedAnchors[0].download).toMatch(/^carefold-cardiology-guide-prep-\d{4}-\d{2}-\d{2}\.json$/);
      expect(revokedUrls).toHaveLength(1);
    });
  });
});
