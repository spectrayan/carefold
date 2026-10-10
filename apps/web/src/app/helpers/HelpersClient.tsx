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

import React, { useState, useMemo, useEffect, useRef } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import {
  Search,
  Shield,
  Stethoscope,
  FileText,
  HeartPulse,
  Check,
  MessageSquare,
  Plus
} from 'lucide-react';
import type { AgentSummary } from '@/lib/types';
import type { SkillSummary } from '@/types/api';
export type { SkillSummary };
import {
  cn,
  sanitizeAgentDescription,
  formatRiskClass,
  formatCareStage
} from '@/lib/utils';
import { Segmented } from '@/components/ui/Segmented';
import { Button } from '@/components/ui/Button';
import { AgentFormModal } from '@/components/agents/AgentFormModal';
import { SkillFormModal } from '@/components/skills/SkillFormModal';

export interface HelpersClientProps {
  initialAgents: AgentSummary[];
  initialCategories?: Record<string, any> | null;
  initialSkills: SkillSummary[];
  activeProfileId?: string;
  activeProfileName?: string;
}

function resolveAgentIcon(id?: string): React.ComponentType<{ className?: string }> {
  if (id === 'visit-steward') return Stethoscope;
  if (id === 'benefits-guide' || id === 'claims-appeals-guide') return FileText;
  if (id === 'habit-companion') return HeartPulse;
  if (id?.includes('cardio')) return HeartPulse;
  return Shield;
}

export function HelpersClient({
  initialAgents,
  initialSkills,
  activeProfileId = 'me',
  activeProfileName = 'Me'
}: HelpersClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [agents, setAgents] = useState<AgentSummary[]>(initialAgents);
  const [skills, setSkills] = useState<SkillSummary[]>(initialSkills);

  const [isCreateAgentOpen, setIsCreateAgentOpen] = useState(false);
  const [isCreateSkillOpen, setIsCreateSkillOpen] = useState(false);

  useEffect(() => {
    setAgents(initialAgents);
  }, [initialAgents]);

  useEffect(() => {
    setSkills(initialSkills);
  }, [initialSkills]);

  // Tab state: "assistants" vs "skills"
  const [activeTab, setActiveTab] = useState<'assistants' | 'skills'>(() => {
    return searchParams.get('tab') === 'skills' ? 'skills' : 'assistants';
  });

  const handleTabChange = (val: string) => {
    const nextTab = val === 'skills' ? 'skills' : 'assistants';
    setActiveTab(nextTab);
    const params = new URLSearchParams(searchParams.toString());
    if (val === 'skills') {
      params.set('tab', 'skills');
    } else {
      params.delete('tab');
    }
    const newQuery = params.toString() ? `?${params.toString()}` : '';
    router.replace(`/helpers${newQuery}`, { scroll: false });
  };

  const [search, setSearch] = useState('');
  const [selectedCareStage, setSelectedCareStage] = useState('all');
  const [forCaregivers, setForCaregivers] = useState(false);
  const [selectedRisk, setSelectedRisk] = useState('all');
  const [selectedDomain, setSelectedDomain] = useState('all');

  // Global "/" keyboard shortcut to focus search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        document.activeElement?.tagName !== 'INPUT' &&
        document.activeElement?.tagName !== 'TEXTAREA'
      ) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Filter assistants
  const filteredAgents = useMemo(() => {
    return agents.filter((agent) => {
      if (agent.hidden) return false;

      // Search keyword
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const matchesTitle = agent.title?.toLowerCase().includes(q);
        const matchesDesc = agent.description?.toLowerCase().includes(q);
        const matchesId = agent.id.toLowerCase().includes(q);
        if (!matchesTitle && !matchesDesc && !matchesId) return false;
      }

      // Risk Class
      if (selectedRisk !== 'all' && agent.risk_class !== selectedRisk) {
        return false;
      }

      // Care Stage
      if (selectedCareStage !== 'all') {
        const stages = (agent.care_stages || []).map((s) => s.toLowerCase());
        if (!stages.includes(selectedCareStage.toLowerCase())) {
          return false;
        }
      }

      // Caregiver flag
      if (forCaregivers) {
        const aud = (agent.target_audience || []).map((a) => a.toLowerCase());
        if (!aud.includes('caregivers')) {
          return false;
        }
      }

      return true;
    });
  }, [agents, search, selectedRisk, selectedCareStage, forCaregivers]);

  // Filter skills
  const filteredSkills = useMemo(() => {
    return skills.filter((skill) => {
      if (skill.id === '_template' || skill.id.startsWith('_') || skill.id.startsWith('.')) {
        return false;
      }

      if (search.trim()) {
        const q = search.trim().toLowerCase();
        const matchesTitle = skill.title?.toLowerCase().includes(q);
        const matchesName = skill.name.toLowerCase().includes(q);
        const matchesDesc = skill.description?.toLowerCase().includes(q);
        if (!matchesTitle && !matchesName && !matchesDesc) return false;
      }

      if (selectedRisk !== 'all' && skill.risk_class !== selectedRisk) {
        return false;
      }

      if (selectedDomain !== 'all') {
        if (!skill.domain || skill.domain.toLowerCase() !== selectedDomain.toLowerCase()) {
          return false;
        }
      }

      return true;
    });
  }, [skills, search, selectedRisk, selectedDomain]);

  return (
    <div className="max-w-[var(--cf-content-wide)] mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Header with Title and Segmented Switcher */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-[var(--cf-fg)]">
            Care Helpers & Skills
          </h1>
          <p className="text-sm text-[var(--cf-fg-muted)] mt-1 max-w-2xl">
            Specialist helpers run on this computer, use only the tools they list, and never diagnose.
          </p>
        </div>

        {/* Action Button & Segmented Control */}
        <div className="shrink-0 flex flex-wrap items-center gap-3">
          {activeTab === 'assistants' ? (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setIsCreateAgentOpen(true)}
              leftIcon={<Plus className="w-4 h-4" />}
            >
              Create Agent
            </Button>
          ) : (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setIsCreateSkillOpen(true)}
              leftIcon={<Plus className="w-4 h-4" />}
            >
              Create Skill
            </Button>
          )}

          <Segmented
            aria-label="Helpers category selection"
            value={activeTab}
            onChange={handleTabChange}
            options={[
              {
                value: 'assistants',
                label: 'Assistants',
                badge: agents.filter((a) => !a.hidden).length
              },
              {
                value: 'skills',
                label: 'Skill Packs',
                badge: skills.filter((s) => s.id !== '_template' && !s.id.startsWith('_')).length
              }
            ]}
          />
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl p-4 mb-6 shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-[var(--cf-fg-subtle)] absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            ref={searchInputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search helpers or skills..."
            className="w-full h-10 pl-10 pr-12 text-sm rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all"
          />
          <kbd className="absolute right-3 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[10px] font-mono font-medium rounded border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]">
            /
          </kbd>
        </div>

        {/* Filter Controls for Assistants */}
        {activeTab === 'assistants' ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mr-1">
              When:
            </span>
            {[
              { id: 'all', label: 'Any time' },
              { id: 'pre_visit', label: 'Before a visit' },
              { id: 'during_visit', label: 'At the visit' },
              { id: 'post_visit', label: 'After a visit' },
              { id: 'daily_living', label: 'Day to day' }
            ].map((stage) => {
              const isSelected = selectedCareStage === stage.id;
              return (
                <button
                  key={stage.id}
                  type="button"
                  onClick={() => setSelectedCareStage(stage.id)}
                  className={cn(
                    'px-3 py-1.5 rounded-full text-xs font-medium transition-all min-h-[36px]',
                    isSelected
                      ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] font-semibold shadow-sm ring-1 ring-emerald-500/20'
                      : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)]'
                  )}
                >
                  {stage.label}
                </button>
              );
            })}

            {/* Caregivers Checkbox Chip */}
            <button
              type="button"
              onClick={() => setForCaregivers((prev) => !prev)}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all min-h-[36px] ml-1',
                forCaregivers
                  ? 'bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 font-semibold ring-1 ring-emerald-500/30'
                  : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
              )}
            >
              <Check className={cn('w-3.5 h-3.5', forCaregivers ? 'opacity-100' : 'opacity-0')} />
              <span>For caregivers</span>
            </button>

            {/* Safety Level Dropdown */}
            <select
              value={selectedRisk}
              onChange={(e) => setSelectedRisk(e.target.value)}
              aria-label="Safety level"
              className="h-9 px-3 text-xs rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[36px]"
            >
              <option value="all">All safety levels</option>
              <option value="wellness">Everyday wellness</option>
              <option value="admin">Paperwork & navigation</option>
              <option value="clinical_assist">Clinical prep · asks consent</option>
            </select>
          </div>
        ) : (
          /* Filter Controls for Skills */
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] mr-1">
              Domain:
            </span>
            {['all', 'clinical', 'navigation', 'wellness', 'therapy', 'education'].map((dom) => {
              const isSelected = selectedDomain === dom;
              return (
                <button
                  key={dom}
                  type="button"
                  onClick={() => setSelectedDomain(dom)}
                  className={cn(
                    'px-3 py-1.5 rounded-full text-xs font-medium transition-all min-h-[36px]',
                    isSelected
                      ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] font-semibold shadow-sm'
                      : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
                  )}
                >
                  {dom.charAt(0).toUpperCase() + dom.slice(1)}
                </button>
              );
            })}

            <select
              value={selectedRisk}
              onChange={(e) => setSelectedRisk(e.target.value)}
              aria-label="Skill risk level"
              className="h-9 px-3 text-xs rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[36px]"
            >
              <option value="all">All risk classes</option>
              <option value="wellness">Wellness</option>
              <option value="admin">Admin</option>
              <option value="clinical_assist">Clinical assist</option>
              <option value="education">Education</option>
            </select>
          </div>
        )}
      </div>

      {/* Catalog Grid */}
      {activeTab === 'assistants' ? (
        filteredAgents.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center p-12 bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl mb-10">
            <Search className="w-8 h-8 text-[var(--cf-fg-subtle)] mb-3" />
            <h3 className="text-base font-semibold text-[var(--cf-fg)] mb-1">No helpers found</h3>
            <p className="text-xs text-[var(--cf-fg-muted)] mb-4">
              No assistants match your search criteria. Try adjusting your query or filters.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch('');
                setSelectedCareStage('all');
                setSelectedRisk('all');
                setForCaregivers(false);
              }}
            >
              Reset filters
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mb-10">
            {filteredAgents.map((agent) => {
              const Icon = resolveAgentIcon(agent.id);
              const isClinical = agent.risk_class === 'clinical_assist';
              const isWellness = agent.risk_class === 'wellness';
              const isAdmin = agent.risk_class === 'admin';

              return (
                <article
                  key={agent.id}
                  className="flex flex-col justify-between p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] hover:border-[var(--cf-border-strong)] shadow-sm hover:shadow-md transition-all group"
                >
                  <div>
                    {/* Top row: Icon, Name, Tier badge */}
                    <div className="flex items-start gap-3.5 mb-3">
                      <div className="w-10 h-10 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] flex items-center justify-center text-[var(--cf-fg)] shrink-0">
                        <Icon className="w-5 h-5" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h2 className="text-base font-semibold text-[var(--cf-fg)] truncate">
                          {agent.title}
                        </h2>
                        {/* Safety Tier Badge */}
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full mt-1',
                            isClinical &&
                              'bg-amber-50 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60',
                            isWellness &&
                              'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60',
                            isAdmin &&
                              'bg-sky-50 dark:bg-sky-950/60 text-sky-800 dark:text-sky-300 border border-sky-200 dark:border-sky-800/60'
                          )}
                        >
                          <Shield className="w-3 h-3" />
                          {isClinical
                            ? 'Clinical prep · asks consent'
                            : isWellness
                            ? 'Everyday wellness'
                            : 'Paperwork & navigation'}
                        </span>
                      </div>
                    </div>

                    {/* Sanitized Plain-Language Description */}
                    <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mb-4 line-clamp-3">
                      {sanitizeAgentDescription(agent.description)}
                    </p>

                    {/* Care Stage Tags */}
                    {agent.care_stages && agent.care_stages.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mb-4">
                        {agent.care_stages.slice(0, 3).map((stage) => (
                          <span
                            key={stage}
                            className="text-[10px] font-medium px-2 py-0.5 rounded-md bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]"
                          >
                            {formatCareStage(stage)}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Footer with Skills metadata & Chat Action */}
                  <div className="pt-3 border-t border-[var(--cf-border)] flex items-center justify-between gap-2 mt-auto">
                    <span className="text-[11px] text-[var(--cf-fg-subtle)] truncate">
                      Skills: {agent.skills?.slice(0, 2).join(', ') || 'base'}
                    </span>
                    <Link
                      href={`/p/${activeProfileId}/chat?agent=${agent.id}`}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-[var(--cf-surface-2)] text-[var(--cf-fg)] hover:bg-[var(--cf-primary-soft)] hover:text-[var(--cf-primary-soft-fg)] transition-all min-h-[36px]"
                    >
                      <MessageSquare className="w-3.5 h-3.5" />
                      <span>Chat for {activeProfileName}</span>
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        )
      ) : (
        /* Skill Packs Tab */
        filteredSkills.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-center p-12 bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl mb-10">
            <Search className="w-8 h-8 text-[var(--cf-fg-subtle)] mb-3" />
            <h3 className="text-base font-semibold text-[var(--cf-fg)] mb-1">No helpers found</h3>
            <p className="text-xs text-[var(--cf-fg-muted)] mb-4">
              No skill packs match your search criteria. Try adjusting your query or filters.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearch('');
                setSelectedDomain('all');
                setSelectedRisk('all');
              }}
            >
              Reset filters
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 mb-10">
            {filteredSkills.map((skill) => {
              return (
                <article
                  key={skill.id}
                  className="flex flex-col justify-between p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] hover:border-[var(--cf-border-strong)] shadow-sm hover:shadow-md transition-all group"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <h2 className="text-base font-semibold text-[var(--cf-fg)] truncate">
                        {skill.title || skill.name}
                      </h2>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)]">
                        v{skill.version}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)]">
                        {skill.domain || 'clinical'}
                      </span>
                      <span className="text-[11px] text-[var(--cf-fg-subtle)]">
                        {formatRiskClass(skill.risk_class)}
                      </span>
                    </div>

                    <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mb-4 line-clamp-3">
                      {skill.description || 'Reference clinical workflow pack and guidelines.'}
                    </p>
                  </div>

                  <div className="pt-3 border-t border-[var(--cf-border)] flex items-center justify-between text-xs text-[var(--cf-fg-subtle)]">
                    <span>Tools: {skill.tools?.length || 0}</span>
                    <Link
                      href={`/helpers/skills/${skill.id}`}
                      className="font-semibold text-[var(--cf-primary-hover)] hover:underline inline-flex items-center gap-1"
                    >
                      View pack →
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>
        )
      )}

      {/* 3-Column Safety Boundary Section matching helpers.html */}
      <section
        aria-label="How Carefold helpers work safely"
        className="bg-[var(--cf-surface)] border border-[var(--cf-border)] rounded-2xl p-6 shadow-sm"
      >
        <h2 className="text-base font-bold text-[var(--cf-fg)] mb-4">
          How Carefold helpers work safely
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Column 1: Everyday wellness */}
          <div className="flex items-start gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800/60 flex items-center justify-center text-emerald-700 dark:text-emerald-300 shrink-0">
              <HeartPulse className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--cf-fg)]">Everyday wellness</h3>
              <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mt-1">
                Habit tracking, medication routines, and wellness check-ins. No clinical diagnosis.
              </p>
            </div>
          </div>

          {/* Column 2: Paperwork & navigation */}
          <div className="flex items-start gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-sky-50 dark:bg-sky-950/60 border border-sky-200 dark:border-sky-800/60 flex items-center justify-center text-sky-700 dark:text-sky-300 shrink-0">
              <FileText className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--cf-fg)]">Paperwork & navigation</h3>
              <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mt-1">
                Insurance benefits, prior authorizations, bills, and appeals guidance.
              </p>
            </div>
          </div>

          {/* Column 3: Clinical visit preparation */}
          <div className="flex items-start gap-3.5">
            <div className="w-9 h-9 rounded-xl bg-amber-50 dark:bg-amber-950/60 border border-amber-200 dark:border-amber-800/60 flex items-center justify-center text-amber-700 dark:text-amber-300 shrink-0">
              <Stethoscope className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[var(--cf-fg)]">Clinical visit preparation</h3>
              <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed mt-1">
                Visit checklists, question lists, and doctor prep. Requires consent; emergency handoff to 911.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Creation Modals */}
      <AgentFormModal
        isOpen={isCreateAgentOpen}
        onClose={() => setIsCreateAgentOpen(false)}
        onSuccess={(newAgent) => {
          setIsCreateAgentOpen(false);
          setAgents((prev) => [newAgent as any, ...prev]);
          router.refresh();
        }}
        availableSkills={skills}
      />

      <SkillFormModal
        isOpen={isCreateSkillOpen}
        onClose={() => setIsCreateSkillOpen(false)}
        onSuccess={(newSkill) => {
          setIsCreateSkillOpen(false);
          setSkills((prev) => [newSkill as any, ...prev]);
          router.refresh();
        }}
      />
    </div>
  );
}
