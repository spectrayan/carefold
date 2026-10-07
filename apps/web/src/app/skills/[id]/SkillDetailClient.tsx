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
import Link from 'next/link';
import {
  ArrowLeft,
  ShieldCheck,
  CheckCircle2,
  FileText,
  Wrench,
  ShieldAlert,
  XCircle,
  FileCode2,
  BookOpen
} from 'lucide-react';
import { formatCategoryLabel, formatRiskClass, formatForbiddenIntent } from '@/lib/utils';
import type { SkillDetailResponse } from '@/types/api';

interface SkillDetailClientProps {
  skill: SkillDetailResponse;
}

export function SkillDetailClient({ skill }: SkillDetailClientProps) {
  const categoryLabel = formatCategoryLabel(skill.category, skill.domain);
  const riskClassLabel = formatRiskClass(skill.risk_class);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Navigation Breadcrumb */}
      <div>
        <Link
          href="/skills"
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-slate-900 dark:text-zinc-400 dark:hover:text-zinc-100 transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Skills catalog</span>
        </Link>
      </div>

      {/* Hero Banner */}
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-4 max-w-3xl">
            {/* Badges Row */}
            <div className="flex flex-wrap items-center gap-2">
              {skill.domain && (
                <span className="text-xs uppercase font-bold tracking-wider px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border border-slate-200/60 dark:border-zinc-700/60">
                  {String(skill.domain)}
                </span>
              )}

              {categoryLabel && (
                <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60">
                  {categoryLabel}
                </span>
              )}

              {riskClassLabel && (
                <span className="text-xs font-medium px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400">
                  {riskClassLabel}
                </span>
              )}

              {skill.is_verified !== false && (
                <span
                  data-testid="skill-detail-verified"
                  className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60"
                >
                  <ShieldCheck className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
                  <span>Verified Skill</span>
                </span>
              )}

              {skill.has_evals && (
                <span
                  data-testid="skill-detail-evals"
                  className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60"
                >
                  <CheckCircle2 className="w-3.5 h-3.5 text-purple-600 dark:text-purple-400" />
                  <span>Has Evals</span>
                </span>
              )}

              {skill.version && (
                <span className="text-xs font-mono text-slate-400 dark:text-zinc-500">
                  v{skill.version}
                </span>
              )}
            </div>

            {/* Title & Description */}
            <div>
              <h1 className="text-3xl font-extrabold text-slate-900 dark:text-zinc-100 tracking-tight">
                {skill.name}
              </h1>
              <p className="mt-3 text-sm text-slate-600 dark:text-zinc-300 leading-relaxed">
                {skill.description || 'No description provided for this skill.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Non-Clinical Safety Disclaimer Banner */}
      <div
        role="region"
        aria-label="Clinical Safety Boundary"
        className="rounded-2xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/40 p-4 text-amber-900 dark:text-amber-200 text-xs flex items-start gap-3 shadow-sm"
      >
        <ShieldAlert className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" aria-hidden="true" />
        <div className="space-y-0.5 leading-relaxed">
          <p className="font-semibold text-amber-950 dark:text-amber-100">
            Clinical Safety Boundary & Non-Diagnostic Scope
          </p>
          <p>
            This skill provides structured administrative and visit-preparation guidelines. Carefold agents executing this
            skill will never formulate formal medical diagnoses, recommend prescription alterations, calculate medication
            dosages, or replace emergency triage. Always consult licensed healthcare professionals for clinical decisions.
          </p>
        </div>
      </div>

      {/* Detail Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Column: Operating Instructions & Clinical Protocol */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Operating Instructions & Protocol</span>
            </h2>
            <div
              data-testid="skill-instructions-content"
              className="text-xs text-slate-700 dark:text-zinc-300 leading-relaxed max-h-[640px] overflow-y-auto bg-slate-50/70 dark:bg-zinc-800/60 p-5 rounded-xl border border-slate-200/60 dark:border-zinc-700/60 font-mono whitespace-pre-wrap select-text"
            >
              {skill.instructions ? (
                skill.instructions
              ) : (
                <span className="italic text-slate-400 dark:text-zinc-500">
                  No operating instructions text bundled in this skill manifest.
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Sidebar Column: References, Tools, and Safety Boundaries */}
        <div className="space-y-6">
          {/* Bundled Reference Documents */}
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
              <FileText className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              <span>Reference Documents ({skill.references?.length || 0})</span>
            </h2>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Clinical guidelines, questionnaires, and checklists bundled with this skill:
            </p>

            {skill.references && skill.references.length > 0 ? (
              <div data-testid="skill-references-list" className="space-y-2">
                {skill.references.map((refDoc) => (
                  <div
                    key={refDoc}
                    className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-50 dark:bg-zinc-800/80 border border-slate-200/70 dark:border-zinc-700/70 text-xs font-mono text-slate-800 dark:text-zinc-200"
                  >
                    <FileCode2 className="w-4 h-4 text-blue-500 dark:text-blue-400 shrink-0" />
                    <span className="truncate">{refDoc}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div
                data-testid="skill-references-empty"
                className="p-4 rounded-xl bg-slate-50 dark:bg-zinc-800/60 border border-dashed border-slate-200 dark:border-zinc-700 text-xs text-slate-500 dark:text-zinc-400 italic text-center"
              >
                No static reference documents declared for this skill.
              </div>
            )}
          </div>

          {/* Permitted Sandbox Tools */}
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
              <Wrench className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <span>Permitted Sandbox Tools</span>
            </h2>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Tools permitted for agents executing this skill pack:
            </p>

            <div data-testid="skill-tools-list" className="flex flex-wrap gap-2">
              {skill.tools && skill.tools.length > 0 ? (
                skill.tools.map((tool) => (
                  <span
                    key={tool}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-mono bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
                  >
                    <span>{tool}</span>
                  </span>
                ))
              ) : (
                <span className="text-xs text-slate-400 dark:text-zinc-500 italic">
                  No sandbox tools declared.
                </span>
              )}
            </div>
          </div>

          {/* Forbidden Intent Guardrails */}
          <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-900 dark:text-zinc-100 uppercase tracking-wider flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-600 dark:text-amber-400" />
              <span>Forbidden Intent Guardrails</span>
            </h2>
            <p className="text-xs text-slate-500 dark:text-zinc-400">
              Actions strictly blocked at the runtime guardrail gate:
            </p>

            <div data-testid="skill-forbidden-list" className="space-y-2.5">
              {skill.forbidden && skill.forbidden.length > 0 ? (
                skill.forbidden.map((token) => (
                  <div
                    key={token}
                    className="flex items-start gap-2.5 p-3 rounded-xl bg-amber-50/60 dark:bg-amber-950/30 border border-amber-200/70 dark:border-amber-900/50 text-xs"
                  >
                    <XCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                    <div className="space-y-0.5">
                      <p className="font-semibold text-amber-900 dark:text-amber-200">
                        {formatForbiddenIntent(token)}
                      </p>
                      <p className="font-mono text-[10px] text-amber-700/80 dark:text-amber-400/80">
                        Token: {token}
                      </p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-400 dark:text-zinc-500 italic">
                  Standard repository non-clinical safety boundaries apply.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
