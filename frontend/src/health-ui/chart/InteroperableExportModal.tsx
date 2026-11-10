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

'use client';

import React, { useEffect, useRef, useState } from 'react';
import {
  Download,
  FileJson,
  Database,
  ShieldAlert,
  CheckCircle2,
  X,
} from 'lucide-react';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { downloadBlob } from '../../lib/dossierExport';
import type { EhrExportFormat, EhrExportResult } from '../../types/ehrChart';

export interface InteroperableExportModalProps {
  isOpen: boolean;
  profileId: string;
  onClose: () => void;
  onExport: (format: EhrExportFormat, confirmed: boolean) => Promise<EhrExportResult>;
}

const EXPORT_FORMAT_OPTIONS: ReadonlyArray<{
  format: EhrExportFormat;
  title: string;
  extensionLabel: string;
  operationLabel: string;
  description: string;
}> = [
  {
    format: 'ips_json',
    title: 'HL7 International Patient Summary (IPS) Bundle',
    extensionLabel: '.json',
    operationLabel: 'GET /Patient/{id}/$summary',
    description:
      'Document Bundle (LOINC 60591-5) containing Active Problems, Medications, Allergies, Immunizations, and Diagnostic Results.',
  },
  {
    format: 'everything_json',
    title: 'FHIR R4 Patient $everything Longitudinal Bundle',
    extensionLabel: '.json',
    operationLabel: 'GET /Patient/{id}/$everything',
    description:
      'Complete profile-scoped FHIR R4 searchset Bundle across all clinical resources for portable sharing.',
  },
  {
    format: 'bulk_ndjson',
    title: 'Bulk FHIR R4 NDJSON Stream',
    extensionLabel: '.ndjson',
    operationLabel: 'POST /Patient/{id}/$export',
    description:
      'Newline-delimited FHIR R4 JSON (application/fhir+ndjson) suitable for bulk archival and analytics tools.',
  },
];

export function InteroperableExportModal({
  isOpen,
  profileId,
  onClose,
  onExport,
}: InteroperableExportModalProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<EhrExportFormat>('ips_json');
  const [userConfirmed, setUserConfirmed] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [lastExportResult, setLastExportResult] = useState<EhrExportResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (isOpen) {
      setUserConfirmed(false);
      setLastExportResult(null);
      setErrorMsg(null);
      if (typeof dialog.showModal === 'function' && !dialog.open) {
        try {
          dialog.showModal();
        } catch {
          dialog.setAttribute('open', '');
        }
      } else {
        dialog.setAttribute('open', '');
      }
    } else if (dialog.open) {
      if (typeof dialog.close === 'function') {
        dialog.close();
      } else {
        dialog.removeAttribute('open');
      }
    }
  }, [isOpen]);

  // Progressive enhancement fallback for <dialog closedby="any"> where native closedBy is absent
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || !isOpen) return;

    const handleNativeClose = () => {
      dialog.returnValue = '';
      onClose();
    };
    dialog.addEventListener('close', handleNativeClose);

    const hasNativeClosedBy =
      typeof HTMLDialogElement !== 'undefined' &&
      'closedBy' in HTMLDialogElement.prototype;

    let pressedOutside = false;
    const isPointerOutside = (e: PointerEvent) => {
      const rect = dialog.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      return (
        e.clientX < rect.left ||
        e.clientX > rect.right ||
        e.clientY < rect.top ||
        e.clientY > rect.bottom
      );
    };
    const handlePointerDown = (e: PointerEvent) => {
      pressedOutside = isPointerOutside(e);
    };
    const handlePointerUp = (e: PointerEvent) => {
      if (pressedOutside && isPointerOutside(e)) {
        onClose();
      }
    };

    if (!hasNativeClosedBy) {
      dialog.addEventListener('pointerdown', handlePointerDown);
      dialog.addEventListener('pointerup', handlePointerUp);
    }

    return () => {
      dialog.removeEventListener('close', handleNativeClose);
      if (!hasNativeClosedBy) {
        dialog.removeEventListener('pointerdown', handlePointerDown);
        dialog.removeEventListener('pointerup', handlePointerUp);
      }
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleTriggerExport = async () => {
    if (!userConfirmed) {
      setErrorMsg(
        'Please confirm that you want to export unencrypted health records to your device.'
      );
      return;
    }
    setIsExporting(true);
    setErrorMsg(null);
    try {
      const result = await onExport(selectedFormat, true);
      setLastExportResult(result);
      const blob = new Blob([result.content], { type: result.mimeType });
      downloadBlob(blob, result.filename);
    } catch (err: any) {
      setErrorMsg(err?.message || 'Unable to generate clinical export bundle.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      {...({ closedby: 'any' } as any)}
      aria-labelledby="interoperable-export-title"
      data-testid="interoperable-export-modal"
      data-profile-id={profileId}
      className="w-full max-w-xl rounded-[var(--cf-radius-lg)] bg-[var(--cf-surface)] text-[var(--cf-fg)] border border-[var(--cf-border)] shadow-xl p-0 text-start overscroll-contain backdrop:bg-black/50 backdrop:overscroll-contain backdrop:overflow-hidden"
    >
      {/* Modal Header */}
      <div className="px-5 py-4 border-b border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <FileJson className="w-4 h-4 text-[var(--cf-primary)]" aria-hidden="true" />
            <h2 id="interoperable-export-title" className="text-base font-bold text-[var(--cf-fg)]">
              Interoperable FHIR R4 &amp; IPS Export
            </h2>
          </div>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Download standards-compliant HL7 IPS or FHIR R4 clinical bundles for profile{' '}
            <code className="font-mono">{profileId}</code>.
          </p>
        </div>

        <Button
          variant="ghost"
          size="sm"
          aria-label="Close export modal"
          data-testid="close-export-modal-btn"
          onClick={onClose}
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </Button>
      </div>

      {/* Modal Content */}
      <div className="p-5 space-y-4">
        <div className="space-y-2.5" role="radiogroup" aria-label="Select export format">
          {EXPORT_FORMAT_OPTIONS.map((opt) => {
            const isSelected = selectedFormat === opt.format;
            return (
              <button
                key={opt.format}
                type="button"
                role="radio"
                aria-checked={isSelected}
                data-testid={`export-format-option-${opt.format}`}
                onClick={() => {
                  setSelectedFormat(opt.format);
                  setErrorMsg(null);
                }}
                className={`w-full p-3.5 rounded-[var(--cf-radius-md)] border text-start transition-all ${
                  isSelected
                    ? 'bg-[var(--cf-primary-soft)] border-2 border-[var(--cf-primary)]'
                    : 'bg-[var(--cf-surface-2)] border-[var(--cf-border)] hover:border-[var(--cf-border-strong)]'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-[var(--cf-fg)] flex items-center gap-2">
                    <Database className="w-4 h-4 text-[var(--cf-primary)]" aria-hidden="true" />
                    {opt.title}
                  </span>
                  <div className="flex items-center gap-1.5">
                    <Badge variant="info" size="sm">
                      {opt.extensionLabel}
                    </Badge>
                    <Badge variant="neutral" size="sm">
                      {opt.operationLabel}
                    </Badge>
                  </div>
                </div>
                <p className="text-xs text-[var(--cf-fg-muted)] mt-1">{opt.description}</p>
              </button>
            );
          })}
        </div>

        {/* User Confirmation Gate (X-Carefold-Confirm: true) */}
        <div className="p-3.5 rounded-[var(--cf-radius-md)] bg-[var(--cf-warn-bg)] border border-[var(--cf-warn-border)] text-[var(--cf-warn-fg)] space-y-2">
          <div className="flex items-center gap-2 text-xs font-semibold">
            <ShieldAlert className="w-4 h-4 shrink-0" aria-hidden="true" />
            <span>User-Confirmed Clinical Export &amp; Audit Notice</span>
          </div>
          <p className="text-xs leading-relaxed">
            Exported FHIR files contain unencrypted personal health information (PHI) and are
            recorded in Carefold&apos;s tamper-evident SHA-256 hash-chained audit log.
          </p>
          <label className="flex items-center gap-2 text-xs font-medium cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={userConfirmed}
              data-testid="export-confirm-checkbox"
              onChange={(e) => {
                setUserConfirmed(e.target.checked);
                if (e.target.checked) setErrorMsg(null);
              }}
              className="rounded border-[var(--cf-border-strong)]"
            />
            <span>
              I confirm exporting this health record (<code className="font-mono">X-Carefold-Confirm: true</code>)
            </span>
          </label>
        </div>

        {errorMsg && (
          <p
            role="alert"
            data-testid="export-error-alert"
            className="text-xs font-medium text-[var(--cf-danger-fg)]"
          >
            {errorMsg}
          </p>
        )}

        {lastExportResult && (
          <div
            data-testid="export-success-banner"
            className="p-3 rounded-[var(--cf-radius-md)] bg-[var(--cf-success-bg)] border border-[var(--cf-success-border)] text-[var(--cf-success-fg)] flex items-center justify-between gap-2 text-xs"
          >
            <span className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 className="w-4 h-4 shrink-0" aria-hidden="true" />
              Downloaded {lastExportResult.filename} ({lastExportResult.resourceCount} FHIR resources)
            </span>
          </div>
        )}
      </div>

      {/* Modal Footer */}
      <div className="px-5 py-3.5 border-t border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex items-center justify-end gap-2">
        <Button
          variant="secondary"
          size="sm"
          autoFocus
          data-testid="cancel-export-btn"
          onClick={onClose}
        >
          Cancel
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={isExporting}
          data-testid="confirm-download-export-btn"
          onClick={handleTriggerExport}
        >
          <Download className="w-3.5 h-3.5 me-1.5" aria-hidden="true" />
          Download Export
        </Button>
      </div>
    </dialog>
  );
}
