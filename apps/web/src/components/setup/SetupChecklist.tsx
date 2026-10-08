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

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  Copy,
  Check,
  ExternalLink,
  ArrowRight,
  Stethoscope,
  Cloud,
  Server
} from 'lucide-react';
import { cn } from '@/lib/utils';
import {
  runSetupDiagnostics,
  markSetupComplete,
  type SetupDiagnosticsResult,
  type SetupCheckItem
} from '@/lib/setup';

export interface SetupChecklistProps {
  isSettingsView?: boolean;
  onDismiss?: () => void;
  className?: string;
}

function CopyButton({ text, testId }: { text: string; testId?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard) {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // Fallback if clipboard API is unavailable
    }
  };

  return (
    <button
      type="button"
      data-testid={testId || 'copy-command-btn'}
      aria-label={`Copy command ${text}`}
      onClick={handleCopy}
      className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-medium rounded-md bg-white dark:bg-zinc-700 border border-slate-200 dark:border-zinc-600 text-slate-700 dark:text-zinc-200 hover:bg-slate-50 dark:hover:bg-zinc-600 transition cursor-pointer"
    >
      {copied ? (
        <>
          <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
          <span className="text-emerald-700 dark:text-emerald-300">Copied</span>
        </>
      ) : (
        <>
          <Copy className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-400" />
          <span>Copy</span>
        </>
      )}
    </button>
  );
}

function StepStatusIcon({ status, isCloud }: { status: SetupCheckItem['status']; isCloud?: boolean }) {
  if (status === 'checking') {
    return <RotateCcw className="w-5 h-5 text-slate-400 dark:text-zinc-500 animate-spin shrink-0" />;
  }
  if (status === 'pass') {
    if (isCloud) {
      return <Cloud className="w-5 h-5 text-sky-600 dark:text-sky-400 shrink-0" />;
    }
    return <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />;
  }
  if (status === 'warn') {
    return <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0" />;
  }
  return <XCircle className="w-5 h-5 text-rose-600 dark:text-rose-400 shrink-0" />;
}

function StepBadge({ badge }: { badge: SetupCheckItem['badge'] }) {
  let badgeStyles = 'bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border-slate-200 dark:border-zinc-700';
  if (badge === '[READY]') {
    badgeStyles = 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
  } else if (badge === '[CLOUD ACTIVE]') {
    badgeStyles = 'bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800';
  } else if (badge === '[MISSING MODEL]' || badge === '[API KEY MISSING]') {
    badgeStyles = 'bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800';
  } else if (badge === '[OFFLINE]') {
    badgeStyles = 'bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800';
  }

  return (
    <span
      data-testid="status-badge"
      className={cn(
        'text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full border uppercase',
        badgeStyles
      )}
    >
      {badge}
    </span>
  );
}

export function SetupChecklist({
  isSettingsView = false,
  onDismiss,
  className
}: SetupChecklistProps) {
  const [diagnostics, setDiagnostics] = useState<SetupDiagnosticsResult | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [statusAnnouncement, setStatusAnnouncement] = useState('');

  const checkConnectivity = useCallback(async () => {
    setIsChecking(true);
    setStatusAnnouncement('Checking system connectivity and model status...');
    try {
      const result = await runSetupDiagnostics();
      setDiagnostics(result);
      if (result.allPassed) {
        setStatusAnnouncement('All connectivity checks passed. System ready.');
      } else {
        setStatusAnnouncement(
          `Checks finished: Backend is ${result.backend.status}, Model is ${result.model.status}.`
        );
      }
    } catch {
      setStatusAnnouncement('Diagnostics failed to execute.');
    } finally {
      setIsChecking(false);
    }
  }, []);

  useEffect(() => {
    checkConnectivity();
  }, [checkConnectivity]);

  const handleStarterClick = () => {
    if (!isSettingsView) {
      markSetupComplete('true');
      onDismiss?.();
    }
  };

  return (
    <div
      data-testid="setup-checklist"
      className={cn('space-y-4', className)}
    >
      {/* Live announcement region for accessibility */}
      <div
        role="status"
        aria-live="polite"
        className="sr-only"
        data-testid="setup-status-announcement"
      >
        {statusAnnouncement}
      </div>

      {/* Checklist Header Bar */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-zinc-800">
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-zinc-100 flex items-center gap-2">
            <Server className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>{isSettingsView ? 'System Diagnostics & Connectivity' : 'First-Run Setup Checklist'}</span>
          </h3>
          <p className="text-xs text-slate-500 dark:text-zinc-400 mt-0.5">
            {isSettingsView
              ? 'Verify local runtime health and Ollama model availability anytime'
              : 'Ensure local backend and inference services are active before clinical consultation'}
          </p>
        </div>

        <button
          type="button"
          data-testid="setup-recheck-btn"
          aria-label="Re-check connectivity status"
          disabled={isChecking}
          onClick={checkConnectivity}
          className={cn(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition cursor-pointer',
            isChecking
              ? 'bg-slate-100 dark:bg-zinc-800 text-slate-400 dark:text-zinc-500 border-slate-200 dark:border-zinc-700 cursor-not-allowed'
              : 'bg-white dark:bg-zinc-800 text-slate-700 dark:text-zinc-200 border-slate-200 dark:border-zinc-700 hover:bg-slate-50 dark:hover:bg-zinc-700'
          )}
        >
          <RotateCcw className={cn('w-3.5 h-3.5', isChecking && 'animate-spin text-emerald-600 dark:text-emerald-400')} />
          <span>{isChecking ? 'Checking...' : 'Re-check'}</span>
        </button>
      </div>

      {/* Step 1: Backend API Status */}
      <div
        data-testid="setup-step-backend"
        className={cn(
          'p-3.5 rounded-xl border transition-colors',
          diagnostics?.backend.status === 'pass'
            ? 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200/80 dark:border-emerald-800/50'
            : diagnostics?.backend.status === 'fail'
            ? 'bg-rose-50/50 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-800/50'
            : 'bg-slate-50 dark:bg-zinc-800/40 border-slate-200 dark:border-zinc-800'
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <StepStatusIcon status={diagnostics?.backend.status ?? 'checking'} />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                  1. Backend API Runtime
                </span>
                <StepBadge badge={diagnostics?.backend.badge ?? '[CHECKING]'} />
              </div>
              <p className="text-xs text-slate-600 dark:text-zinc-300 mt-1">
                {diagnostics?.backend.message ?? 'Probing backend runtime on port 8010...'}
              </p>

              {diagnostics?.backend.details && (
                <div className="mt-1 text-[11px] text-slate-500 dark:text-zinc-400">
                  {diagnostics.backend.details.map((d, idx) => (
                    <span key={idx} className="block">{d}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Remediation code box if backend is failing */}
        {diagnostics?.backend.status === 'fail' && diagnostics.backend.fixCommand && (
          <div className="mt-3 pt-2.5 border-t border-rose-200/60 dark:border-rose-800/40 space-y-2">
            <span className="text-[11px] font-semibold text-rose-900 dark:text-rose-300 block">
              Actionable Fix:
            </span>
            <div className="flex items-center justify-between gap-2 p-2 rounded-lg bg-white dark:bg-zinc-900 border border-rose-200 dark:border-rose-900/60 font-mono text-xs text-slate-800 dark:text-zinc-200">
              <span className="truncate">{diagnostics.backend.fixCommand}</span>
              <CopyButton text={diagnostics.backend.fixCommand} testId="copy-backend-command" />
            </div>
            {diagnostics.backend.secondaryCommand && (
              <p className="text-[11px] text-slate-500 dark:text-zinc-400">
                Or launch coordinator: <code className="font-mono text-xs text-slate-700 dark:text-zinc-300">{diagnostics.backend.secondaryCommand}</code>
              </p>
            )}
            {diagnostics.backend.docsLink && (
              <a
                href={diagnostics.backend.docsLink}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:underline"
              >
                <span>{diagnostics.backend.docsLabel || 'View Setup Documentation'}</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Step 2: Model & Provider Status */}
      <div
        data-testid="setup-step-model"
        className={cn(
          'p-3.5 rounded-xl border transition-colors',
          diagnostics?.model.status === 'pass'
            ? diagnostics.isCloudActive
              ? 'bg-sky-50/50 dark:bg-sky-950/20 border-sky-200/80 dark:border-sky-800/50'
              : 'bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-200/80 dark:border-emerald-800/50'
            : diagnostics?.model.status === 'warn'
            ? 'bg-amber-50/50 dark:bg-amber-950/20 border-amber-200/80 dark:border-amber-800/50'
            : diagnostics?.model.status === 'fail'
            ? 'bg-rose-50/50 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-800/50'
            : 'bg-slate-50 dark:bg-zinc-800/40 border-slate-200 dark:border-zinc-800'
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <StepStatusIcon
              status={diagnostics?.model.status ?? 'checking'}
              isCloud={diagnostics?.isCloudActive && diagnostics?.model.status === 'pass'}
            />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                  2. {diagnostics?.model.title || 'Inference Model & Provider'}
                </span>
                <StepBadge badge={diagnostics?.model.badge ?? '[CHECKING]'} />
              </div>
              <p className="text-xs text-slate-600 dark:text-zinc-300 mt-1">
                {diagnostics?.model.message ?? 'Probing model provider availability...'}
              </p>

              {diagnostics?.model.details && (
                <div className="mt-1.5 space-y-0.5 text-[11px] text-slate-500 dark:text-zinc-400">
                  {diagnostics.model.details.map((d, idx) => (
                    <span key={idx} className="block leading-relaxed">{d}</span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Remediation code box if Ollama is failing or models missing */}
        {diagnostics?.model.fixCommand && (
          <div
            className={cn(
              'mt-3 pt-2.5 border-t space-y-2',
              diagnostics.model.status === 'fail'
                ? 'border-rose-200/60 dark:border-rose-800/40'
                : 'border-amber-200/60 dark:border-amber-800/40'
            )}
          >
            <span
              className={cn(
                'text-[11px] font-semibold block',
                diagnostics.model.status === 'fail'
                  ? 'text-rose-900 dark:text-rose-300'
                  : 'text-amber-900 dark:text-amber-300'
              )}
            >
              Actionable Fix:
            </span>
            <div className="flex items-center justify-between gap-2 p-2 rounded-lg bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-700 font-mono text-xs text-slate-800 dark:text-zinc-200">
              <span className="truncate">{diagnostics.model.fixCommand}</span>
              <CopyButton text={diagnostics.model.fixCommand} testId="copy-model-command" />
            </div>
            {diagnostics.model.docsLink && (
              <a
                href={diagnostics.model.docsLink}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-400 hover:underline"
              >
                <span>{diagnostics.model.docsLabel || 'View Setup Documentation'}</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Step 3: Starters Verification & Try a Starter */}
      <div
        data-testid="setup-step-starters"
        className="p-3.5 rounded-xl border bg-slate-50 dark:bg-zinc-800/40 border-slate-200 dark:border-zinc-800 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3"
      >
        <div className="flex items-start gap-2.5">
          <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-slate-900 dark:text-zinc-100">
                3. Flagship Agent Starters
              </span>
              <StepBadge badge="[READY]" />
            </div>
            <p className="text-xs text-slate-600 dark:text-zinc-300 mt-1">
              Visit Steward is ready with pre-configured appointment preparation questions.
            </p>
          </div>
        </div>

        <Link
          href="/chat?agent=visit-steward"
          data-testid="setup-starter-btn"
          onClick={handleStarterClick}
          className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition whitespace-nowrap cursor-pointer shrink-0"
        >
          <Stethoscope className="w-3.5 h-3.5" />
          <span>Try a starter</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>
    </div>
  );
}
