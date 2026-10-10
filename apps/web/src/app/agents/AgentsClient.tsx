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
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import {
  Search,
  Shield,
  Stethoscope,
  FileText,
  HeartPulse,
  Check,
  MessageSquare,
  Plus,
  Sparkles
} from 'lucide-react';
import type { AgentSummary } from '@/lib/types';
import type { SkillSummary } from '@/types/api';
import {
  cn,
  sanitizeAgentDescription,
  formatRiskClass
} from '@/lib/utils';
import { profilePath } from '@/lib/routes';
import { Segmented } from '@/components/ui/Segmented';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
import { AgentFormModal } from '@/components/agents/AgentFormModal';
import { SkillFormModal } from '@/components/skills/SkillFormModal';

export interface AgentsClientProps {
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

export function AgentsClient({
  initialAgents,
  initialSkills,
  activeProfileId = 'me',
  activeProfileName = 'Me'
}: AgentsClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchInputRef = useRef<HTMLInputElement>(null);

  const [agents, setAgents] = useState<AgentSummary[]>(initialAgents);
  const [skills, setSkills] = useState<SkillSummary[]>(initialSkills);

  const [isCreateAgentOpen, setIsCreateAgentOpen] = useState(false);
  const [isCreateSkillOpen, setIsCreateSkillOpen] = useState(false);

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
    const basePath = pathname.startsWith('/helpers') ? '/helpers' : '/agents';
    router.replace(`${basePath}${newQuery}`, { scroll: false });
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
      {/* Header with Title, Segmented Switcher & Creation Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-[var(--cf-fg)]">
            Agents &amp; Skills
          </h1>
          <p className="text-sm text-[var(--cf-fg-muted)] mt-1 max-w-2xl">
            Specialist agents and clinical skill packs running on this computer. Private, task-scoped, and zero cloud telemetry.
          </p>
        </div>

        {/* Action Button & Segmented Control */}
        <div className="flex flex-wrap items-center gap-3">
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
            aria-label="Agents or skills selection"
            value={activeTab}
            onChange={handleTabChange}
            options={[
              {
                value: 'assistants',
                label: 'Agents',
                badge: filteredAgents.length
              },
              {
                value: 'skills',
                label: 'Skills',
                badge: filteredSkills.length
              }
            ]}
          />
        </div>
      </div>

      {/* Search Input */}
      <div className="relative mb-5">
        <Search className="w-4 h-4 text-[var(--cf-fg-subtle)] absolute left-3.5 top-1/2 -translate-y-1/2" />
        <input
          ref={searchInputRef}
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${activeTab === 'assistants' ? 'agents' : 'skills'} by name, keyword, or domain... (Press / to focus)`}
          aria-label="Search agents and skills"
          className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-sm text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] transition-all min-h-[44px]"
        />
      </div>

      {/* Filter Row */}
      {activeTab === 'assistants' ? (
        <div className="flex flex-wrap items-center gap-2 mb-6 text-xs">
          <span className="font-semibold text-[var(--cf-fg-subtle)] uppercase tracking-wider mr-1">
            Filter:
          </span>

          {/* Care Stage Filters */}
          {[
            { id: 'all', label: 'Any time' },
            { id: 'pre_visit', label: 'Before visit' },
            { id: 'during_visit', label: 'At visit' },
            { id: 'post_visit', label: 'After visit' },
            { id: 'daily_living', label: 'Day to day' }
          ].map((stage) => {
            const isSelected = selectedCareStage === stage.id;
            return (
              <Chip
                key={stage.id}
                size="md"
                selected={isSelected}
                onClick={() => setSelectedCareStage(stage.id)}
                className={isSelected ? 'font-semibold shadow-sm' : ''}
              >
                {stage.label}
              </Chip>
            );
          })}

          {/* Risk Filters */}
          {[
            { id: 'all', label: 'All Risk Levels' },
            { id: 'clinical_assist', label: 'Clinical prep' },
            { id: 'admin', label: 'Administrative' },
            { id: 'wellness', label: 'Wellness' }
          ].map((rf) => {
            const isSelected = selectedRisk === rf.id;
            return (
              <Chip
                key={rf.id}
                size="md"
                selected={isSelected}
                onClick={() => setSelectedRisk(rf.id)}
                className={isSelected ? 'font-semibold shadow-sm' : ''}
              >
                {rf.label}
              </Chip>
            );
          })}

          {/* Caregiver Toggle */}
          <Chip
            size="md"
            selected={forCaregivers}
            onClick={() => setForCaregivers(!forCaregivers)}
            icon={forCaregivers ? <Check className="w-3.5 h-3.5" /> : undefined}
            className={forCaregivers ? 'font-semibold shadow-sm' : ''}
          >
            For Caregivers
          </Chip>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2 mb-6 text-xs">
          <span className="font-semibold text-[var(--cf-fg-subtle)] uppercase tracking-wider mr-1">
            Domain:
          </span>

          {[
            { id: 'all', label: 'All Domains' },
            { id: 'clinical', label: 'Clinical' },
            { id: 'navigation', label: 'Navigation' },
            { id: 'wellness', label: 'Wellness' }
          ].map((df) => {
            const isSelected = selectedDomain === df.id;
            return (
              <Chip
                key={df.id}
                size="md"
                selected={isSelected}
                onClick={() => setSelectedDomain(df.id)}
                className={isSelected ? 'font-semibold shadow-sm' : ''}
              >
                {df.label}
              </Chip>
            );
          })}
        </div>
      )}

      {/* Main Grid Content */}
      {activeTab === 'assistants' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredAgents.map((agent) => {
            const Icon = resolveAgentIcon(agent.id);
            const isClinical = agent.risk_class === 'clinical_assist';

            return (
              <div
                key={agent.id}
                className="p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm flex flex-col justify-between transition-all hover:border-[var(--cf-border-strong)] gap-4"
              >
                <div>
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div className="w-10 h-10 rounded-xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-200 dark:border-emerald-800/60 flex items-center justify-center text-emerald-700 dark:text-emerald-300 shrink-0">
                      <Icon className="w-5 h-5" />
                    </div>
                    <span
                      className={cn(
                        'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold',
                        isClinical
                          ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20'
                          : 'bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border border-[var(--cf-border)]'
                      )}
                    >
                      {formatRiskClass(agent.risk_class)}
                    </span>
                  </div>

                  <h2 className="text-base font-bold text-[var(--cf-fg)] tracking-tight">
                    {agent.title}
                  </h2>
                  <p className="text-xs text-[var(--cf-fg-muted)] mt-1.5 line-clamp-2 leading-relaxed">
                    {sanitizeAgentDescription(agent.description)}
                  </p>
                </div>

                <div className="pt-3 border-t border-[var(--cf-border)] flex items-center justify-between gap-2">
                  <Link
                    href={`/agents/${agent.id}`}
                    className="text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] transition min-h-[36px] inline-flex items-center"
                  >
                    View details
                  </Link>

                  <Link
                    href={profilePath(activeProfileId, `chat?agent=${encodeURIComponent(agent.id)}`)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-emerald-700 hover:bg-emerald-800 text-white dark:bg-emerald-500 dark:text-[#04201a] shadow-sm transition min-h-[36px]"
                  >
                    <MessageSquare className="w-3.5 h-3.5" />
                    <span>Consult for {activeProfileName}</span>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredSkills.map((skill) => (
            <div
              key={skill.id}
              className="p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm flex flex-col justify-between transition-all hover:border-[var(--cf-border-strong)] gap-4"
            >
              <div>
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="w-10 h-10 rounded-xl bg-purple-50 dark:bg-purple-950/60 border border-purple-200 dark:border-purple-800/60 flex items-center justify-center text-purple-700 dark:text-purple-300 shrink-0">
                    <Sparkles className="w-5 h-5" />
                  </div>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border border-[var(--cf-border)]">
                    {formatRiskClass(skill.risk_class)}
                  </span>
                </div>

                <h2 className="text-base font-bold text-[var(--cf-fg)] tracking-tight">
                  {skill.title || skill.name}
                </h2>
                <p className="text-xs text-[var(--cf-fg-muted)] mt-1.5 line-clamp-2 leading-relaxed">
                  {skill.description}
                </p>
              </div>

              <div className="pt-3 border-t border-[var(--cf-border)] flex items-center justify-between">
                <span className="text-xs text-[var(--cf-fg-subtle)] capitalize">
                  {skill.domain || 'Clinical'} skill pack
                </span>
                <Link
                  href={`/skills/${skill.id}`}
                  className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline min-h-[36px] inline-flex items-center"
                >
                  Skill documentation &rarr;
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

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
