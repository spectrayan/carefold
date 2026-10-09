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

import React, { useState, useMemo } from 'react';
import Link from 'next/link';
import {
  Search,
  Sparkles,
  ShieldCheck,
  CheckCircle2,
  FileCheck2,
  Wrench,
  AlertCircle,
  X,
  ArrowRight,
  ShieldAlert,
  Plus
} from 'lucide-react';
import { cn, formatCategoryLabel, formatRiskClass } from '@/lib/utils';
import type { SkillSummary } from '@/types/api';
import { SkillFormModal } from '@/components/skills/SkillFormModal';

interface SkillsClientProps {
  initialSkills: SkillSummary[];
}

export function SkillsClient({ initialSkills }: SkillsClientProps) {
  const [skills, setSkills] = useState<SkillSummary[]>(initialSkills);
  const [search, setSearch] = useState('');
  const [selectedDomain, setSelectedDomain] = useState('all');
  const [selectedRisk, setSelectedRisk] = useState('all');
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // Defensively exclude _template and private/hidden entries
  const productionSkills = useMemo(() => {
    return skills.filter(
      (s) => s.id !== '_template' && !s.id.startsWith('_') && !s.id.startsWith('.')
    );
  }, [skills]);

  // Extract distinct domains from installed skills, ordered canonically
  const domainFilters = useMemo(() => {
    const list = [{ id: 'all', label: 'All Domains' }];
    const canonicalOrder = ['clinical', 'navigation', 'wellness', 'therapy', 'education'];
    const presentDomains = Array.from(
      new Set(productionSkills.map((s) => (s.domain ? String(s.domain).toLowerCase() : '')))
    ).filter(Boolean);

    const sorted = presentDomains.sort((a, b) => {
      const idxA = canonicalOrder.indexOf(a);
      const idxB = canonicalOrder.indexOf(b);
      if (idxA !== -1 && idxB !== -1) return idxA - idxB;
      if (idxA !== -1) return -1;
      if (idxB !== -1) return 1;
      return a.localeCompare(b);
    });

    for (const d of sorted) {
      list.push({
        id: d,
        label: d.charAt(0).toUpperCase() + d.slice(1)
      });
    }
    return list;
  }, [productionSkills]);

  const riskFilters = [
    { id: 'all', label: 'All Risks' },
    { id: 'wellness', label: 'Wellness' },
    { id: 'admin', label: 'Admin' },
    { id: 'clinical_assist', label: 'Clinical assist' },
    { id: 'education', label: 'Education' }
  ];

  const filteredSkills = useMemo(() => {
    return productionSkills.filter((skill) => {
      // 1. Search keyword matching
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const matches =
          (skill.title && skill.title.toLowerCase().includes(q)) ||
          skill.name.toLowerCase().includes(q) ||
          skill.id.toLowerCase().includes(q) ||
          (skill.description && skill.description.toLowerCase().includes(q)) ||
          (skill.category && skill.category.toLowerCase().includes(q)) ||
          (skill.domain && String(skill.domain).toLowerCase().includes(q)) ||
          (skill.tags && skill.tags.some((t) => t.toLowerCase().includes(q))) ||
          (skill.tools && skill.tools.some((tool) => tool.toLowerCase().includes(q)));
        if (!matches) return false;
      }

      // 2. Domain filter
      if (selectedDomain !== 'all') {
        const d = skill.domain ? String(skill.domain).toLowerCase() : '';
        if (d !== selectedDomain.toLowerCase()) return false;
      }

      // 3. Risk Class filter
      if (selectedRisk !== 'all') {
        const r = skill.risk_class ? String(skill.risk_class).toLowerCase() : '';
        if (r !== selectedRisk.toLowerCase()) return false;
      }

      return true;
    });
  }, [productionSkills, search, selectedDomain, selectedRisk]);

  const handleResetFilters = () => {
    setSearch('');
    setSelectedDomain('all');
    setSelectedRisk('all');
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Hero Section */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-slate-200 dark:border-zinc-800 pb-6">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 mb-3">
            <Sparkles className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
            <span>Modular Clinical & Navigational Skills</span>
          </div>
          <h1 className="text-3xl font-extrabold text-slate-900 dark:text-zinc-100 tracking-tight">
            Skills Catalog
          </h1>
          <p className="mt-2 text-sm text-slate-600 dark:text-zinc-400 max-w-2xl leading-relaxed">
            Browse verified clinical protocols, visit preparation checklists, and insurance navigation packs
            powering Carefold specialist agents.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Create Skill</span>
          </button>

          <div className="flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-zinc-400 bg-slate-50 dark:bg-zinc-800/80 px-3.5 py-2 rounded-xl border border-slate-200/80 dark:border-zinc-700/80 shrink-0">
            <FileCheck2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <span>{filteredSkills.length} of {productionSkills.length} skills listed</span>
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
            Non-Clinical Information & Preparation Aids
          </p>
          <p>
            Carefold skills provide structured information, visit checklists, and navigation protocols.
            Skills never formulate medical diagnoses, prescribe treatments, calculate drug dosages, or replace emergency care.
          </p>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-4 shadow-sm space-y-4">
        {/* Search Input */}
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-zinc-500" />
          <input
            type="text"
            data-testid="skills-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills by name, description, category, or tool..."
            className="w-full pl-10 pr-10 py-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50/50 dark:bg-zinc-800/50 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500 transition"
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-zinc-300 p-1"
              aria-label="Clear search"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Filter Controls */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-1">
          {/* Domain Tabs */}
          <div
            className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0"
            data-testid="skills-domain-filters"
            role="group"
            aria-label="Filter by domain"
          >
            <span className="text-xs font-semibold text-slate-400 dark:text-zinc-500 mr-1 uppercase tracking-wider shrink-0">
              Domain:
            </span>
            {domainFilters.map((df) => (
              <button
                key={df.id}
                type="button"
                aria-pressed={selectedDomain === df.id}
                onClick={() => setSelectedDomain(df.id)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition min-h-[36px] sm:min-h-0',
                  selectedDomain === df.id
                    ? 'bg-emerald-600 dark:bg-emerald-500 text-white shadow-sm'
                    : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700 hover:text-slate-900 dark:hover:text-zinc-100'
                )}
              >
                {df.label}
              </button>
            ))}
          </div>

          {/* Risk Class Filters */}
          <div
            className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0"
            data-testid="skills-risk-filters"
            role="group"
            aria-label="Filter by risk class"
          >
            <span className="text-xs font-semibold text-slate-400 dark:text-zinc-500 mr-1 uppercase tracking-wider shrink-0">
              Risk:
            </span>
            {riskFilters.map((rf) => (
              <button
                key={rf.id}
                type="button"
                aria-pressed={selectedRisk === rf.id}
                onClick={() => setSelectedRisk(rf.id)}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition min-h-[36px] sm:min-h-0',
                  selectedRisk === rf.id
                    ? 'bg-slate-900 dark:bg-zinc-100 text-white dark:text-zinc-900 shadow-sm'
                    : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700 hover:text-slate-900 dark:hover:text-zinc-100'
                )}
              >
                {rf.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Skills Grid */}
      {filteredSkills.length === 0 ? (
        <div
          data-testid="skills-empty-state"
          className="text-center py-16 bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-8 space-y-4"
        >
          <AlertCircle className="w-12 h-12 text-slate-300 dark:text-zinc-600 mx-auto" />
          <div className="space-y-1">
            <h3 className="text-base font-bold text-slate-800 dark:text-zinc-200">
              No matching skills found
            </h3>
            <p className="text-xs text-slate-500 dark:text-zinc-400 max-w-sm mx-auto">
              No skill packs match your current search query or active filter criteria.
            </p>
          </div>
          <button
            type="button"
            onClick={handleResetFilters}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-100 dark:bg-zinc-800 hover:bg-slate-200 dark:hover:bg-zinc-700 text-slate-700 dark:text-zinc-300 text-xs font-semibold transition"
          >
            Reset all filters
          </button>
        </div>
      ) : (
        <div
          data-testid="skills-grid"
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5"
        >
          {filteredSkills.map((skill) => {
            const categoryLabel = formatCategoryLabel(skill.category, skill.domain);
            const riskClassLabel = formatRiskClass(skill.risk_class);

            return (
              <Link
                key={skill.id}
                href={`/skills/${encodeURIComponent(skill.id)}`}
                data-testid={`skill-card-${skill.id}`}
                className="group flex flex-col justify-between bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 hover:border-emerald-300 dark:hover:border-emerald-700 rounded-2xl p-5 shadow-sm hover:shadow-md transition duration-200"
              >
                <div className="space-y-3">
                  {/* Badges Bar */}
                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Domain Badge */}
                    {skill.domain && (
                      <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border border-slate-200/60 dark:border-zinc-700/60">
                        {String(skill.domain)}
                      </span>
                    )}

                    {/* Category Specialty Badge */}
                    {categoryLabel && (
                      <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60">
                        {categoryLabel}
                      </span>
                    )}

                    {/* Risk Class Badge */}
                    {riskClassLabel && (
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400">
                        {riskClassLabel}
                      </span>
                    )}

                    {/* Verified Badge */}
                    {skill.is_verified !== false && (
                      <span
                        data-testid="badge-verified"
                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60"
                      >
                        <ShieldCheck className="w-3 h-3 text-blue-600 dark:text-blue-400" />
                        <span>Verified</span>
                      </span>
                    )}

                    {/* Has Evals Badge */}
                    {skill.has_evals && (
                      <span
                        data-testid="badge-has-evals"
                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/60"
                      >
                        <CheckCircle2 className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                        <span>Has evals</span>
                      </span>
                    )}
                  </div>

                  {/* Title & Version */}
                  <div>
                    <div className="flex items-center justify-between gap-2">
                      <h2 className="text-base font-bold text-slate-900 dark:text-zinc-100 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition">
                        {skill.title || skill.name}
                      </h2>
                      {skill.version && (
                        <span className="text-[11px] font-mono text-slate-400 dark:text-zinc-500 shrink-0">
                          v{skill.version}
                        </span>
                      )}
                    </div>

                    <p className="mt-1.5 text-xs text-slate-600 dark:text-zinc-400 leading-relaxed line-clamp-3">
                      {skill.description || 'No description provided.'}
                    </p>
                  </div>
                </div>

                {/* Footer / Tools Row */}
                <div className="mt-4 pt-3 border-t border-slate-100 dark:border-zinc-800/80 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-1.5 overflow-hidden">
                    <Wrench className="w-3.5 h-3.5 text-slate-400 dark:text-zinc-500 shrink-0" />
                    <span className="text-[11px] font-mono text-slate-500 dark:text-zinc-400 truncate">
                      {skill.tools && skill.tools.length > 0 ? skill.tools.join(', ') : 'no tools'}
                    </span>
                  </div>

                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 group-hover:translate-x-0.5 transition shrink-0 ml-2">
                    <span>View details</span>
                    <ArrowRight className="w-3 h-3" />
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Create Skill Modal */}
      <SkillFormModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSuccess={(newSkill) => {
          setSkills((prev) => [
            {
              id: newSkill.id,
              name: newSkill.name,
              title: newSkill.title,
              description: newSkill.description,
              version: newSkill.version,
              risk_class: newSkill.risk_class,
              tools: newSkill.tools,
              domain: newSkill.domain,
              category: newSkill.category,
              tags: newSkill.tags,
              is_verified: newSkill.is_verified,
            },
            ...prev,
          ]);
        }}
      />
    </div>
  );
}
