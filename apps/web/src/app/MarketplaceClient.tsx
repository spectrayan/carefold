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
import * as LucideIcons from 'lucide-react';
import {
  Search,
  Sparkles,
  AlertCircle,
  ArrowRight,
  Shield,
  Stethoscope,
  FileText,
  HeartPulse,
  Terminal,
  Users,
  RotateCcw,
} from 'lucide-react';
import type { AgentSummary } from '@/lib/types';
import {
  cn,
  sanitizeAgentDescription,
  formatCategoryLabel,
  formatRiskClass,
  formatCareStage,
} from '@/lib/utils';

function resolveAgentIcon(iconToken?: string, id?: string): React.ComponentType<{ className?: string }> {
  if (iconToken && iconToken in LucideIcons) {
    const IconComp = (LucideIcons as Record<string, any>)[iconToken];
    if (typeof IconComp === 'function' || typeof IconComp === 'object') {
      return IconComp;
    }
  }
  if (id === 'visit-steward') return Stethoscope;
  if (id === 'benefits-guide') return FileText;
  if (id === 'habit-companion') return HeartPulse;
  return Shield;
}

export function MarketplaceClient({
  initialAgents,
  initialCategories,
}: {
  initialAgents: AgentSummary[];
  initialCategories?: Record<string, any> | null;
}) {
  const [search, setSearch] = useState('');
  const [selectedRisk, setSelectedRisk] = useState<string>('all');
  const [selectedDomain, setSelectedDomain] = useState<string>('all');
  const [selectedCareStage, setSelectedCareStage] = useState<string>('all');
  const [forCaregivers, setForCaregivers] = useState(false);

  const riskFilters = [
    { id: 'all', label: 'All Agents' },
    { id: 'wellness', label: 'Wellness' },
    { id: 'admin', label: 'Admin' },
    { id: 'education', label: 'Education' },
    { id: 'clinical_assist', label: 'Clinical Assist' },
  ];

  // Derive available domains dynamically: only domains with count > 0 are rendered
  const availableDomains = useMemo(() => {
    if (initialCategories?.domains && typeof initialCategories.domains === 'object') {
      const active = Object.entries(initialCategories.domains)
        .filter(([_, data]: [string, any]) => (data?.count ?? 0) > 0)
        .map(([domain]) => domain.toLowerCase());
      if (active.length > 0) {
        return active;
      }
    }

    // Offline fallback derived from initialAgents
    const fallbackSet = new Set<string>();
    for (const agent of initialAgents) {
      if (!agent.hidden && agent.domain) {
        fallbackSet.add(agent.domain.toLowerCase());
      }
    }
    return Array.from(fallbackSet);
  }, [initialCategories, initialAgents]);

  const domainFilters = useMemo(() => {
    const list = [{ id: 'all', label: 'All Domains' }];
    const canonicalOrder = ['navigation', 'wellness', 'clinical', 'therapy', 'education'];
    const sorted = Array.from(new Set(availableDomains)).sort((a, b) => {
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
        label: d.charAt(0).toUpperCase() + d.slice(1),
      });
    }
    return list;
  }, [availableDomains]);

  const careStageFilters = [
    { id: 'all', label: 'All Stages' },
    { id: 'pre_visit', label: 'Before visit' },
    { id: 'during_visit', label: 'During visit' },
    { id: 'post_visit', label: 'After visit' },
    { id: 'follow_up', label: 'Follow-up' },
    { id: 'daily_living', label: 'Daily living' },
  ];

  const filteredAgents = useMemo(() => {
    return initialAgents.filter((agent) => {
      if (agent.hidden) return false;

      // 1. Keyword search (case-insensitive across name, id, description, category, tags, skills)
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const matchesSearch =
          (agent.title && agent.title.toLowerCase().includes(q)) ||
          (agent.id && agent.id.toLowerCase().includes(q)) ||
          (agent.description && agent.description.toLowerCase().includes(q)) ||
          (agent.category && agent.category.toLowerCase().includes(q)) ||
          (agent.tags && agent.tags.some((t) => t.toLowerCase().includes(q))) ||
          (agent.skills && agent.skills.some((s) => s.toLowerCase().includes(q)));
        if (!matchesSearch) return false;
      }

      // 2. Risk Class (AND)
      if (selectedRisk !== 'all') {
        if (!agent.risk_class || agent.risk_class.toLowerCase() !== selectedRisk.toLowerCase()) {
          return false;
        }
      }

      // 3. Domain (AND)
      if (selectedDomain !== 'all') {
        if (!agent.domain || agent.domain.toLowerCase() !== selectedDomain.toLowerCase()) {
          return false;
        }
      }

      // 4. Care Stage ("When") (AND)
      if (selectedCareStage !== 'all') {
        const stages = agent.care_stages || [];
        const matchesStage = stages.some(
          (s) => s.toLowerCase() === selectedCareStage.toLowerCase()
        );
        if (!matchesStage) return false;
      }

      // 5. Target Audience ("For caregivers") (AND)
      if (forCaregivers) {
        const audience = agent.target_audience || [];
        const matchesCaregiver = audience.some(
          (ta) => ta.toLowerCase() === 'caregiver'
        );
        if (!matchesCaregiver) return false;
      }

      return true;
    });
  }, [initialAgents, search, selectedRisk, selectedDomain, selectedCareStage, forCaregivers]);

  const hasActiveFilters =
    search.trim().length > 0 ||
    selectedRisk !== 'all' ||
    selectedDomain !== 'all' ||
    selectedCareStage !== 'all' ||
    forCaregivers;

  const clearAllFilters = () => {
    setSearch('');
    setSelectedRisk('all');
    setSelectedDomain('all');
    setSelectedCareStage('all');
    setForCaregivers(false);
  };

  const getRiskBadgeStyle = (riskClass: string) => {
    switch (riskClass) {
      case 'wellness':
        return 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800';
      case 'admin':
        return 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800';
      case 'education':
        return 'bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800';
      case 'clinical_assist':
        return 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-800';
      default:
        return 'bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border-slate-200 dark:border-zinc-700';
    }
  };

  return (
    <div className="space-y-8">
      {/* Header Banner */}
      <section className="bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-6 sm:p-8 shadow-sm transition-colors">
        <div className="max-w-3xl">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Local Agent Marketplace</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-zinc-100 tracking-tight">
            Specialist Health & Wellness Agents
          </h1>
          <p className="mt-2 text-sm sm:text-base text-slate-600 dark:text-zinc-400 leading-relaxed">
            Discover and interact with private, task-scoped agents running completely on your machine.
            No cloud account, zero prompt retention, and closed tool permissions.
          </p>
        </div>

        {/* Search & Filters */}
        <div className="mt-6 space-y-4" role="search" aria-label="Marketplace agent search and filters">
          <div className="flex flex-col md:flex-row items-stretch md:items-center gap-4">
            <div className="relative flex-1">
              <Search className="w-4 h-4 text-slate-400 dark:text-zinc-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search agents by name, skill, or keyword..."
                aria-label="Search agents by name, skill, or keyword"
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 dark:border-zinc-700 bg-slate-50 dark:bg-zinc-800/70 focus:bg-white dark:focus:bg-zinc-800 text-slate-900 dark:text-zinc-100 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500 text-sm transition"
              />
            </div>

            <div
              className="flex items-center gap-1.5 overflow-x-auto pb-1 md:pb-0"
              data-testid="risk-filters"
              role="group"
              aria-label="Filter by risk class"
            >
              {riskFilters.map((rf) => (
                <button
                  key={rf.id}
                  type="button"
                  aria-pressed={selectedRisk === rf.id}
                  onClick={() => setSelectedRisk(rf.id)}
                  className={cn(
                    'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition',
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

          {/* Domain Filter Pills */}
          <div
            className="flex items-center gap-1.5 overflow-x-auto pt-1 pb-1"
            data-testid="domain-filters"
            role="group"
            aria-label="Filter by domain"
          >
            <span className="text-xs font-semibold text-slate-400 dark:text-zinc-500 mr-1 uppercase tracking-wider">Domain:</span>
            {domainFilters.map((df) => (
              <button
                key={df.id}
                type="button"
                aria-pressed={selectedDomain === df.id}
                onClick={() => setSelectedDomain(df.id)}
                className={cn(
                  'px-3 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition',
                  selectedDomain === df.id
                    ? 'bg-emerald-600 dark:bg-emerald-500 text-white shadow-sm'
                    : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700 hover:text-slate-900 dark:hover:text-zinc-100'
                )}
              >
                {df.label}
              </button>
            ))}
          </div>

          {/* Care Stage ("When") & Caregiver Filters */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2 border-t border-slate-100 dark:border-zinc-800/80">
            <div
              className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0"
              data-testid="care-stage-filters"
              role="group"
              aria-label="Filter by care stage"
            >
              <span className="text-xs font-semibold text-slate-400 dark:text-zinc-500 mr-1 uppercase tracking-wider">When:</span>
              {careStageFilters.map((cs) => (
                <button
                  key={cs.id}
                  type="button"
                  aria-pressed={selectedCareStage === cs.id}
                  onClick={() => setSelectedCareStage(cs.id)}
                  className={cn(
                    'px-3 py-1 rounded-lg text-xs font-medium whitespace-nowrap transition',
                    selectedCareStage === cs.id
                      ? 'bg-blue-600 dark:bg-blue-500 text-white shadow-sm'
                      : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700 hover:text-slate-900 dark:hover:text-zinc-100'
                  )}
                >
                  {cs.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                role="switch"
                aria-checked={forCaregivers}
                aria-label="Filter for caregivers"
                onClick={() => setForCaregivers((prev) => !prev)}
                data-testid="caregiver-filter"
                className={cn(
                  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition select-none',
                  forCaregivers
                    ? 'bg-purple-600 dark:bg-purple-500 text-white shadow-sm ring-1 ring-purple-500/50'
                    : 'bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 hover:bg-slate-200 dark:hover:bg-zinc-700 hover:text-slate-900 dark:hover:text-zinc-100'
                )}
              >
                <Users className="w-3.5 h-3.5" />
                <span>For caregivers</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Agent Grid */}
      {filteredAgents.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-zinc-900 border border-slate-200 dark:border-zinc-800 rounded-2xl p-8">
          <AlertCircle className="w-12 h-12 text-slate-300 dark:text-zinc-600 mx-auto mb-3" />
          <h3 className="text-base font-semibold text-slate-800 dark:text-zinc-200">No agents found</h3>
          <p className="text-sm text-slate-500 dark:text-zinc-400 mt-1 max-w-md mx-auto">
            {hasActiveFilters
              ? 'Try adjusting your search terms or filters.'
              : 'No installed agents were detected in your workspace agents/ folder.'}
          </p>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={clearAllFilters}
              data-testid="clear-all-filters-btn"
              className="mt-4 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-900 dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-slate-800 dark:hover:bg-zinc-200 transition"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Clear all filters</span>
            </button>
          )}
          <div className="mt-6 inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100 dark:bg-zinc-800 rounded-lg text-xs font-mono text-slate-700 dark:text-zinc-300 border border-slate-200 dark:border-zinc-700">
            <Terminal className="w-3.5 h-3.5" />
            <span>carefold agent add visit-steward</span>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredAgents.map((agent) => {
            const Icon = resolveAgentIcon(agent.icon, agent.id);
            const isBundled = Boolean(agent.isBundled ?? agent.is_bundled);
            const isVerified = agent.verified !== false;
            const effectiveTools = agent.effectiveTools || agent.tools || [];
            const skills = agent.skills || [];
            const categoryLabel = formatCategoryLabel(agent.category, agent.domain);
            const isCaregiver = Boolean(
              agent.target_audience &&
                agent.target_audience.some((ta) => ta.toLowerCase() === 'caregiver')
            );
            const careStages = agent.care_stages || [];

            return (
              <div
                key={agent.id}
                className={cn(
                  'bg-white dark:bg-zinc-900 border rounded-2xl p-6 shadow-sm hover:shadow-md transition flex flex-col justify-between group',
                  isVerified
                    ? 'border-slate-200 dark:border-zinc-800 dark:hover:border-zinc-700'
                    : 'border-amber-300 dark:border-amber-800/80 bg-amber-50/20 dark:bg-amber-950/20'
                )}
              >
                <div>
                  {/* Top Badges */}
                  <div className="flex items-start justify-between gap-2 mb-4">
                    <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 flex items-center justify-center text-slate-700 dark:text-zinc-300 group-hover:bg-emerald-50 dark:group-hover:bg-emerald-950/40 group-hover:text-emerald-700 dark:group-hover:text-emerald-300 group-hover:border-emerald-200 dark:group-hover:border-emerald-800 transition">
                      <Icon className="w-6 h-6" />
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                      {agent.domain && (
                        <span
                          data-testid="domain-badge"
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800 capitalize"
                        >
                          {agent.domain}
                        </span>
                      )}
                      {categoryLabel && (
                        <span
                          data-testid="category-badge"
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 border border-slate-200 dark:border-zinc-700"
                        >
                          {categoryLabel}
                        </span>
                      )}
                      {isCaregiver && (
                        <span
                          data-testid="caregiver-badge"
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
                        >
                          Caregiver
                        </span>
                      )}
                      {isBundled && (
                        <span
                          data-testid="bundled-badge"
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-zinc-400 border border-slate-200 dark:border-zinc-700"
                        >
                          Bundled
                        </span>
                      )}
                      {!isVerified && (
                        <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800 flex items-center gap-1">
                          <AlertCircle className="w-3 h-3" />
                          Unverified
                        </span>
                      )}
                      <span
                        className={cn(
                          'text-[11px] font-semibold px-2.5 py-0.5 rounded-full border capitalize',
                          getRiskBadgeStyle(agent.risk_class)
                        )}
                      >
                        {formatRiskClass(agent.risk_class)}
                      </span>
                    </div>
                  </div>

                  {/* Title & Subtitle */}
                  <h2 className="text-lg font-bold text-slate-900 dark:text-zinc-100 group-hover:text-emerald-700 dark:group-hover:text-emerald-400 transition">
                    <Link href={`/agents/${agent.id}`}>{agent.title}</Link>
                  </h2>
                  <p className="mt-2 text-xs sm:text-sm text-slate-600 dark:text-zinc-400 line-clamp-3 leading-relaxed">
                    {sanitizeAgentDescription(agent.description)}
                  </p>

                  {/* Skills, Tools, and Care Stage Pills */}
                  <div className="mt-4 pt-4 border-t border-slate-100 dark:border-zinc-800 space-y-2">
                    {careStages.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600 dark:text-zinc-400">
                        <span className="font-semibold text-slate-700 dark:text-zinc-300">When:</span>
                        {careStages.map((stage) => (
                          <span
                            key={stage}
                            data-testid="care-stage-badge"
                            className="bg-blue-50 dark:bg-blue-950/40 text-blue-800 dark:text-blue-300 px-2 py-0.5 rounded text-[11px] border border-blue-200 dark:border-blue-800/60"
                          >
                            {formatCareStage(stage)}
                          </span>
                        ))}
                      </div>
                    )}

                    <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-zinc-400">
                      <span className="font-semibold text-slate-700 dark:text-zinc-300">Skills:</span>
                      {skills.length > 0 ? (
                        skills.map((skill) => (
                          <span
                            key={skill}
                            className="bg-slate-100 dark:bg-zinc-800 text-slate-700 dark:text-zinc-300 px-2 py-0.5 rounded text-[11px] font-mono border border-transparent dark:border-zinc-700/60"
                          >
                            {skill}
                          </span>
                        ))
                      ) : (
                        <span className="text-slate-400 dark:text-zinc-500 italic">None</span>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-zinc-400">
                      <span className="font-semibold text-slate-700 dark:text-zinc-300">Tools:</span>
                      {effectiveTools.length > 0 ? (
                        effectiveTools.map((t) => (
                          <span
                            key={t}
                            className="bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-300 px-2 py-0.5 rounded text-[11px] font-mono border border-emerald-200 dark:border-emerald-800/60"
                          >
                            {t}
                          </span>
                        ))
                      ) : (
                        <span className="text-slate-400 dark:text-zinc-500 italic">None</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="mt-6 pt-4 border-t border-slate-100 dark:border-zinc-800 flex items-center justify-between gap-3">
                  <Link
                    href={`/agents/${agent.id}`}
                    className="text-xs font-semibold text-slate-600 dark:text-zinc-400 hover:text-slate-900 dark:hover:text-zinc-100 transition"
                  >
                    View Details
                  </Link>

                  <Link
                    href={`/chat?agent=${agent.id}`}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition active:scale-95"
                  >
                    <span>Try in chat</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
