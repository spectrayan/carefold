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

import React, { useState } from 'react';
import {
  UploadCloud,
  FileCode2,
  HeartPulse,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import {
  stageClinicalImport,
  commitImportBatch,
  discardImportBatch,
} from '@/lib/importsClient';
import { ImportStagingReviewTable } from './ImportStagingReviewTable';
import type { ImportBatchResponse, ImportFormat } from '@/types/imports';

export interface ClinicalImportWizardProps {
  profileId: string;
  onImportCommitted?: (batch: ImportBatchResponse) => void;
  className?: string;
}

const FORMAT_OPTIONS: Array<{
  id: ImportFormat;
  label: string;
  subtitle: string;
  defaultSource: string;
}> = [
  {
    id: 'fhir_r4',
    label: 'FHIR R4 Bundle (.json)',
    subtitle: 'Patient, Condition, Medication, Immunization, Allergy & Observation resources',
    defaultSource: 'MyChart FHIR Export',
  },
  {
    id: 'ccda',
    label: 'C-CDA Summary (.xml)',
    subtitle: 'HL7 Continuity of Care Document (Problems, Medications, Allergies, Vitals)',
    defaultSource: 'Hospital C-CDA Portal',
  },
  {
    id: 'apple_health',
    label: 'Apple Health Export (export.xml)',
    subtitle: 'Streaming parser for Vital Signs & Daily Aggregated Activity/Sleep Summaries',
    defaultSource: 'Apple Health',
  },
];

export function ClinicalImportWizard({
  profileId,
  onImportCommitted,
  className,
}: ClinicalImportWizardProps) {
  const [format, setFormat] = useState<ImportFormat>('fhir_r4');
  const [sourceName, setSourceName] = useState<string>('MyChart FHIR Export');
  const [content, setContent] = useState<string>('');
  const [stagedBatch, setStagedBatch] = useState<ImportBatchResponse | null>(null);
  const [committedMessage, setCommittedMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const handleSelectFormat = (nextFormat: ImportFormat) => {
    setFormat(nextFormat);
    const matched = FORMAT_OPTIONS.find((f) => f.id === nextFormat);
    if (matched) {
      setSourceName(matched.defaultSource);
    }
    setError(null);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setContent(text);
      setError(null);
    } catch {
      setError('Unable to read the selected file.');
    }
  };

  const handleStage = async () => {
    if (!content.trim()) {
      setError('Please upload or paste clinical export content to stage.');
      return;
    }
    setIsLoading(true);
    setError(null);
    setCommittedMessage(null);
    try {
      const batch = await stageClinicalImport(profileId, {
        format,
        source_name: sourceName.trim() || 'Clinical Export',
        content,
      });
      setStagedBatch(batch);
    } catch (err: any) {
      setError(err.message || 'Failed to stage clinical import.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCommit = async (batchId: string, selectedIndices: number[]) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await commitImportBatch(profileId, batchId, selectedIndices);
      setStagedBatch(null);
      setContent('');
      setCommittedMessage(
        `Successfully committed ${res.committed_count ?? selectedIndices.length} records from ${res.source_name}.`
      );
      onImportCommitted?.(res);
    } catch (err: any) {
      setError(err.message || 'Failed to commit staged batch.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleDiscard = async (batchId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      await discardImportBatch(profileId, batchId);
      setStagedBatch(null);
    } catch (err: any) {
      setError(err.message || 'Failed to discard staged batch.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      data-testid="clinical-import-wizard"
      className={cn('space-y-4', className)}
    >
      <Card className="p-5 space-y-4 shadow-sm">
        <div className="flex items-center gap-2.5 pb-3 border-b border-[var(--cf-border)]">
          <div className="w-8 h-8 rounded-lg bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
            <UploadCloud className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Clinical &amp; Wearable Record Import Wizard
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Local-first parsing for FHIR R4, C-CDA, and Apple Health with Review-Before-Save staging
            </p>
          </div>
        </div>

        {/* Format Selector */}
        <div
          role="radiogroup"
          aria-label="Clinical import format"
          className="grid grid-cols-1 md:grid-cols-3 gap-2.5"
        >
          {FORMAT_OPTIONS.map((opt) => {
            const active = format === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                role="radio"
                aria-checked={active}
                data-testid={`import-format-${opt.id}`}
                onClick={() => handleSelectFormat(opt.id)}
                className={cn(
                  'p-3 rounded-xl border text-left transition-all space-y-1',
                  active
                    ? 'border-emerald-600 bg-emerald-50/60 dark:bg-emerald-950/30 ring-1 ring-emerald-600'
                    : 'border-[var(--cf-border)] bg-[var(--cf-surface)] hover:bg-[var(--cf-surface-2)]'
                )}
              >
                <div className="flex items-center gap-2 font-semibold text-xs text-[var(--cf-fg)]">
                  {opt.id === 'apple_health' ? (
                    <HeartPulse className="w-4 h-4 text-rose-500" />
                  ) : opt.id === 'ccda' ? (
                    <FileSpreadsheet className="w-4 h-4 text-blue-500" />
                  ) : (
                    <FileCode2 className="w-4 h-4 text-emerald-500" />
                  )}
                  <span>{opt.label}</span>
                </div>
                <p className="text-[11px] text-[var(--cf-fg-muted)] leading-relaxed">
                  {opt.subtitle}
                </p>
              </button>
            );
          })}
        </div>

        {/* Source Name & File / Content Input */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="import-source-name"
              className="block text-xs font-semibold text-[var(--cf-fg)] mb-1"
            >
              Provenance Source Name
            </label>
            <input
              id="import-source-name"
              data-testid="import-source-name-input"
              type="text"
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              placeholder="e.g., MyChart, Apple Health"
              className="w-full px-3 py-2 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)]"
            />
          </div>

          <div>
            <label
              htmlFor="import-file-upload"
              className="block text-xs font-semibold text-[var(--cf-fg)] mb-1"
            >
              Upload Export File (.json / .xml)
            </label>
            <input
              id="import-file-upload"
              data-testid="import-file-input"
              type="file"
              accept=".json,.xml"
              onChange={handleFileUpload}
              className="w-full text-xs text-[var(--cf-fg-muted)] file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-[var(--cf-surface-2)] file:text-[var(--cf-fg)]"
            />
          </div>
        </div>

        <div>
          <label
            htmlFor="import-raw-content"
            className="block text-xs font-semibold text-[var(--cf-fg)] mb-1"
          >
            Or Paste Export Payload
          </label>
          <textarea
            id="import-raw-content"
            data-testid="import-content-textarea"
            rows={4}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste FHIR R4 Bundle JSON, C-CDA XML, or Apple Health XML snippet..."
            className="w-full p-3 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)]"
          />
        </div>

        {error && (
          <div
            data-testid="import-wizard-error"
            className="flex items-center gap-2 p-3 rounded-lg bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-xs text-rose-700 dark:text-rose-300"
          >
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {committedMessage && (
          <div
            data-testid="import-wizard-committed-banner"
            className="flex items-center gap-2 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-xs text-emerald-800 dark:text-emerald-200"
          >
            <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
            <span>{committedMessage}</span>
          </div>
        )}

        <div className="flex justify-end">
          <Button
            variant="primary"
            size="sm"
            loading={isLoading && !stagedBatch}
            disabled={isLoading}
            data-testid="stage-import-btn"
            leftIcon={<UploadCloud className="w-3.5 h-3.5" />}
            onClick={handleStage}
          >
            Stage &amp; Preview Records
          </Button>
        </div>
      </Card>

      {stagedBatch && (
        <ImportStagingReviewTable
          batch={stagedBatch}
          onCommit={handleCommit}
          onDiscard={handleDiscard}
          isSubmitting={isLoading}
        />
      )}
    </div>
  );
}
