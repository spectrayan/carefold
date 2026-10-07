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

import type { ChatMessage } from '@/lib/types';
import type { AgentSummary, AgentDetailResponse } from '@/types/api';

export const NON_CLINICAL_DISCLAIMER_TEXT =
  'Carefold AI agents provide educational context, visit preparation checklists, formulary navigation, and benefits explanation. Agents never provide formal medical diagnoses, drug dosage adjustments, clinical treatment decisions, or acute triage replacement. If you are experiencing a medical emergency, please call 911 or your local emergency services immediately.';

export interface DossierExportOptions {
  agent?: AgentSummary | AgentDetailResponse | null;
  agentId?: string;
  messages: ChatMessage[];
  threadId?: string;
  exportedAt?: Date | string;
}

export interface SanitizedExportMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
}

export interface DossierJsonOutput {
  schema_version: string;
  schemaVersion: string;
  exportedAt: string;
  disclaimer: string;
  session: {
    agentId: string;
    agentTitle: string;
    riskClass: string;
    threadId?: string;
  };
  summary: {
    totalMessages: number;
    userTurns: number;
    assistantTurns: number;
  };
  messages: SanitizedExportMessage[];
}

/**
 * Generates standardized dossier filename matching `carefold-<agent-id>-prep-<YYYY-MM-DD>.<ext>`
 */
export function generateDossierFilename(
  agentId: string,
  format: 'md' | 'json',
  date: Date = new Date()
): string {
  const rawId = (agentId || 'general')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  const cleanId = rawId || 'general';

  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  const dateStr = `${year}-${month}-${day}`;

  return `carefold-${cleanId}-prep-${dateStr}.${format}`;
}

/**
 * Filters sensitive internal trace data, execution outputs, and binary payloads
 * from conversation messages before export.
 */
function sanitizeMessagesForExport(messages: ChatMessage[]): SanitizedExportMessage[] {
  return messages.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content || '',
    ...(m.timestamp ? { timestamp: m.timestamp } : {}),
  }));
}

/**
 * Formats consultation session as a structured Markdown document.
 */
export function formatDossierMarkdown(options: DossierExportOptions): string {
  const { agent, messages, threadId } = options;
  const agentId = options.agentId || agent?.id || 'general';
  const agentTitle = agent?.title || 'Health Assistant';
  const riskClass = agent?.risk_class || 'clinical_assist';

  const exportedAtStr = options.exportedAt
    ? typeof options.exportedAt === 'string'
      ? options.exportedAt
      : options.exportedAt.toISOString()
    : new Date().toISOString();

  const sanitizedMessages = sanitizeMessagesForExport(messages);
  const userTurns = sanitizedMessages.filter((m) => m.role === 'user').length;
  const assistantTurns = sanitizedMessages.filter((m) => m.role === 'assistant').length;

  const lines: string[] = [
    `# Carefold Consultation Dossier — ${agentTitle}`,
    '',
    `> **NON-CLINICAL SAFETY DISCLAIMER**: ${NON_CLINICAL_DISCLAIMER_TEXT}`,
    '',
    '## Session Overview',
    `- **Agent**: ${agentTitle} (\`${agentId}\`)`,
    `- **Risk Class**: ${riskClass}`,
    `- **Exported**: ${exportedAtStr}`,
  ];

  if (threadId) {
    lines.push(`- **Thread ID**: \`${threadId}\``);
  }

  lines.push(
    `- **Total Messages**: ${sanitizedMessages.length} (${userTurns} patient, ${assistantTurns} assistant)`,
    '',
    '---',
    '',
    '## Consultation Transcript',
    ''
  );

  if (sanitizedMessages.length === 0) {
    lines.push('*No consultation messages recorded.*', '');
  } else {
    for (const msg of sanitizedMessages) {
      const timeTag = msg.timestamp ? ` — *${msg.timestamp}*` : '';
      let headerName = 'System Notice';
      if (msg.role === 'user') {
        headerName = 'Patient (User)';
      } else if (msg.role === 'assistant') {
        headerName = `${agentTitle} (Assistant)`;
      }

      lines.push(`### ${headerName}${timeTag}`);
      lines.push('');
      lines.push(msg.content);
      lines.push('');
    }
  }

  return lines.join('\n');
}

/**
 * Formats consultation session as structured JSON conforming to Carefold Dossier Schema v1.0.
 */
export function formatDossierJson(options: DossierExportOptions): string {
  const { agent, messages, threadId } = options;
  const agentId = options.agentId || agent?.id || 'general';
  const agentTitle = agent?.title || 'Health Assistant';
  const riskClass = agent?.risk_class || 'clinical_assist';

  const exportedAtStr = options.exportedAt
    ? typeof options.exportedAt === 'string'
      ? options.exportedAt
      : options.exportedAt.toISOString()
    : new Date().toISOString();

  const sanitizedMessages = sanitizeMessagesForExport(messages);
  const userTurns = sanitizedMessages.filter((m) => m.role === 'user').length;
  const assistantTurns = sanitizedMessages.filter((m) => m.role === 'assistant').length;

  const output: DossierJsonOutput = {
    schema_version: '1.0',
    schemaVersion: '1.0',
    exportedAt: exportedAtStr,
    disclaimer: NON_CLINICAL_DISCLAIMER_TEXT,
    session: {
      agentId,
      agentTitle,
      riskClass,
      ...(threadId ? { threadId } : {}),
    },
    summary: {
      totalMessages: sanitizedMessages.length,
      userTurns,
      assistantTurns,
    },
    messages: sanitizedMessages,
  };

  return JSON.stringify(output, null, 2);
}

/**
 * Triggers pure client-side browser file download from Blob without server roundtrips.
 */
export function downloadBlob(blob: Blob, filename: string): void {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return;
  }

  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';

  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  window.URL.revokeObjectURL(url);
}

/**
 * Orchestrates formatting and client-side download for a given dossier format.
 */
export function exportDossier(
  format: 'md' | 'json',
  options: DossierExportOptions
): void {
  const filename = generateDossierFilename(
    options.agent?.id || options.agentId || 'general',
    format,
    options.exportedAt ? new Date(options.exportedAt) : undefined
  );

  if (format === 'md') {
    const markdownContent = formatDossierMarkdown(options);
    const blob = new Blob([markdownContent], { type: 'text/markdown;charset=utf-8' });
    downloadBlob(blob, filename);
  } else {
    const jsonContent = formatDossierJson(options);
    const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8' });
    downloadBlob(blob, filename);
  }
}
