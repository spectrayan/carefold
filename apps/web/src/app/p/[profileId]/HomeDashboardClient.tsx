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

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  Calendar,
  Sparkles,
  MessageSquare,
  Printer,
  FileText,
  Heart,
  BookOpen,
  Lock,
  ChevronRight,
  Check,
  Activity,
  Edit3,
  Camera
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Avatar, type MemberColorSlot } from '@/components/ui/Avatar';
import { Chip } from '@/components/ui/Chip';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { getHouseholdProfile, fetchHouseholdProfiles } from '@/lib/familyProfiles';
import { useAuth } from '@/lib/auth';
import { profilePath } from '@/lib/routes';
import { ProfileEditModal } from '@/components/family/ProfileEditModal';

export interface CareProfile {
  id: string;
  name: string;
  shortName?: string;
  relationship: string;
  age?: number;
  role?: string;
  colorSlot: MemberColorSlot;
  dateOfBirth?: string;
  avatarUrl?: string;
  viewers?: string[];
}

export interface UpcomingAppointment {
  id: string;
  title: string;
  monthShort: string;
  dayNumber: number;
  timeStr: string;
  clinician: string;
  clinic: string;
  linkedDocTitle?: string;
  specialistId?: string;
  specialistTitle?: string;
  prepCompletedQuestions: number;
  prepTotalQuestions: number;
  checklist: Array<{
    id: string;
    text: string;
    isDone: boolean;
  }>;
  savedToNotesTimestamp?: string;
}

export interface PaperworkDossierSummary {
  id: string;
  title: string;
  facility: string;
  statusBadge: string;
  billedAmount: string;
  planPaidAmount: string;
  patientOwedAmount: string;
}

export interface RoutineHabitItem {
  id: string;
  name: string;
  daysCompleted: boolean[];
  summaryCount: string;
}

export interface RecentClinicalNoteItem {
  id: string;
  title: string;
  authorAgentTitle: string;
  dateFormatted: string;
  slug?: string;
}

export interface HomeDashboardClientProps {
  profileId?: string;
  profile?: CareProfile;
  initialProfile?: CareProfile;
  initialAppointment?: UpcomingAppointment | null;
  initialPaperwork?: PaperworkDossierSummary | null;
  initialRoutines?: RoutineHabitItem[] | null;
  initialNotes?: RecentClinicalNoteItem[] | null;
  isEmpty?: boolean;
}

export function HomeDashboardClient({
  profileId: profileIdProp,
  profile: profileProp,
  initialProfile,
  initialAppointment,
  initialPaperwork,
  initialRoutines,
  initialNotes,
  isEmpty = false
}: HomeDashboardClientProps) {
  const router = useRouter();
  const { user, isLoading, isAuthenticated } = useAuth();
  const [askDraft, setAskDraft] = useState('');
  const [profileOverride, setProfileOverride] = useState<CareProfile | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, router]);

  useEffect(() => {
    fetchHouseholdProfiles().catch(() => {});
  }, []);

  const resolvedInitialProfile = profileProp || initialProfile;
  const profileId = profileIdProp || resolvedInitialProfile?.id || 'me';

  useEffect(() => {
    const handleProfilesChange = () => {
      const updated = getHouseholdProfile(profileId);
      if (updated) {
        setProfileOverride(updated as any);
      }
    };
    window.addEventListener('carefold:household-profiles-changed', handleProfilesChange);
    return () => {
      window.removeEventListener('carefold:household-profiles-changed', handleProfilesChange);
    };
  }, [profileId]);

  // Resolved Profile Info
  const baseProfile: CareProfile = React.useMemo(() => {
    if (resolvedInitialProfile) return resolvedInitialProfile;
    const household = getHouseholdProfile(profileId);
    if (household) {
      return {
        id: household.id,
        name: household.name,
        shortName: household.shortName,
        relationship: household.relationship || 'Self',
        role: household.role || 'Personal care profile',
        colorSlot: household.colorSlot || 1,
        dateOfBirth: household.dateOfBirth,
        avatarUrl: household.avatarUrl,
        viewers: household.viewers
      };
    }
    return {
      id: profileId,
      name: profileId === 'me' ? 'Me' : profileId,
      relationship: 'Self',
      role: 'Personal care profile',
      colorSlot: 1
    };
  }, [resolvedInitialProfile, profileId]);

  const profile: CareProfile = profileOverride || baseProfile;

  const displayName = useMemo(() => {
    const currentName = profile.name?.trim();
    if (currentName && currentName.toLowerCase() !== 'me') {
      return currentName;
    }
    if (user?.full_name?.trim()) {
      return user.full_name.trim();
    }
    if (user?.username?.trim()) {
      return user.username.trim();
    }
    return 'Me';
  }, [profile.name, user?.full_name, user?.username]);

  // Appointment Data (null if isEmpty or not provided)
  const appointment: UpcomingAppointment | null = React.useMemo(() => {
    if (isEmpty) return null;
    if (initialAppointment !== undefined) return initialAppointment;
    return null;
  }, [isEmpty, initialAppointment]);

  // Paperwork Data (null if isEmpty or not provided)
  const paperwork: PaperworkDossierSummary | null = React.useMemo(() => {
    if (isEmpty) return null;
    if (initialPaperwork !== undefined) return initialPaperwork;
    return null;
  }, [isEmpty, initialPaperwork]);

  // Routines Data (null if isEmpty or not provided)
  const routines: RoutineHabitItem[] | null = React.useMemo(() => {
    if (isEmpty) return null;
    if (initialRoutines !== undefined) return initialRoutines;
    return null;
  }, [isEmpty, initialRoutines]);

  // Recent Notes Data (null if isEmpty or not provided)
  const notes: RecentClinicalNoteItem[] | null = React.useMemo(() => {
    if (isEmpty) return null;
    if (initialNotes !== undefined) return initialNotes;
    return null;
  }, [isEmpty, initialNotes]);

  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  }, []);

  const [checklist, setChecklist] = useState(() => appointment?.checklist || []);

  useEffect(() => {
    if (appointment?.checklist) {
      setChecklist(appointment.checklist);
    }
  }, [appointment?.checklist]);

  const handleToggleChecklist = (id: string) => {
    setChecklist((prev) =>
      prev.map((item) => (item.id === id ? { ...item, isDone: !item.isDone } : item))
    );
  };

  const handleAskSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!askDraft.trim()) return;
    router.push(profilePath(profile.id, `chat?prompt=${encodeURIComponent(askDraft.trim())}`));
  };

  const handleStarterClick = (prompt: string) => {
    setAskDraft(prompt);
  };

  const prepPercent = appointment
    ? Math.round((appointment.prepCompletedQuestions / appointment.prepTotalQuestions) * 100)
    : 0;

  return (
    <div className="space-y-6">
      {/* 1. Person Greeting Hero */}
      <section
        aria-label="Person hero"
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 sm:p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
      >
        <div className="flex items-center gap-4">
          <div
            className="relative group cursor-pointer shrink-0"
            onClick={() => setIsEditModalOpen(true)}
            title="Click to edit profile"
            role="button"
            tabIndex={0}
            aria-label="Edit care profile"
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setIsEditModalOpen(true);
              }
            }}
          >
            <Avatar
              name={displayName}
              src={profile.avatarUrl}
              colorSlot={profile.colorSlot}
              size="xl"
              className="shrink-0 transition-transform group-hover:scale-105"
            />
            <div className="absolute inset-0 rounded-full bg-black/35 flex items-center justify-center text-white opacity-0 group-hover:opacity-100 transition-opacity">
              <Camera className="w-5 h-5" />
            </div>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight text-[var(--cf-fg)]">
                {greeting}, {displayName}
              </h1>
              <button
                type="button"
                onClick={() => setIsEditModalOpen(true)}
                aria-label="Edit profile"
                title="Edit profile"
                className="p-1 rounded-lg text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition"
              >
                <Edit3 className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1">
              {profile.role ? `${profile.role} · ` : ''}{profile.relationship}
              {profile.age ? ` · ${profile.age}` : ''}
              {profile.viewers && profile.viewers.length > 0
                ? ` · ${profile.viewers.join(' · ')}`
                : ''}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => setIsEditModalOpen(true)}
            leftIcon={<Edit3 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />}
            className="min-h-[44px]"
          >
            Manage Profile
          </Button>

          <Chip
            size="md"
            variant="neutral"
            icon={<Lock className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />}
          >
            Private on this computer · Only {displayName}&apos;s data shown
          </Chip>
        </div>
      </section>

      {/* 2. Main Asymmetric Two-Column Grid: Next Visit vs Ask about Person */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] gap-6">
        {/* Next Visit Preparation Card */}
        <section
          aria-labelledby="section-next-visit"
          className="flex flex-col justify-between p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
        >
          <div className="flex items-center justify-between pb-3 mb-4 border-b border-[var(--cf-border)]">
            <div className="flex items-center gap-2">
              <Calendar className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <h2 id="section-next-visit" className="text-base font-semibold text-[var(--cf-fg)]">
                Next visit prep
              </h2>
            </div>
            <Link
              href={profilePath(profile.id, 'chat?agent=visit-steward')}
              className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline"
            >
              All visits
            </Link>
          </div>

          {appointment ? (
            <div className="space-y-4">
              {/* Date Badge & Appointment Details */}
              <div className="flex items-start gap-4">
                <div
                  aria-hidden="true"
                  className="w-14 h-14 rounded-xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/40 flex flex-col items-center justify-center shrink-0 shadow-sm"
                >
                  <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-300 uppercase tracking-wider">
                    {appointment.monthShort}
                  </span>
                  <span className="text-xl font-bold text-[var(--cf-fg)] leading-none">
                    {appointment.dayNumber}
                  </span>
                </div>

                <div className="min-w-0 flex-1">
                  <h3 className="text-base font-semibold text-[var(--cf-fg)] truncate">
                    {appointment.title}
                  </h3>
                  <p className="text-xs text-[var(--cf-fg-muted)] mt-0.5">
                    <span>{appointment.timeStr}</span> · <span>{appointment.clinician}</span> · <span>{appointment.clinic}</span>
                  </p>

                  <div className="flex flex-wrap gap-2 mt-2.5">
                    {appointment.linkedDocTitle && (
                      <Chip size="sm" variant="neutral" icon={<FileText className="w-3 h-3" />}>
                        {appointment.linkedDocTitle}
                      </Chip>
                    )}
                    {appointment.specialistTitle && (
                      <Chip size="sm" variant="selected" icon={<Sparkles className="w-3 h-3" />}>
                        {appointment.specialistTitle}
                      </Chip>
                    )}
                  </div>
                </div>
              </div>

              {/* Prep Sheet Progress & Checklist */}
              <div className="p-4 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-[var(--cf-fg)]">Prep sheet</span>
                  <span className="text-[var(--cf-fg-subtle)]">
                    {appointment.prepCompletedQuestions} of {appointment.prepTotalQuestions} questions ready
                  </span>
                </div>

                {/* Accessible Progress Bar */}
                <div
                  role="progressbar"
                  aria-valuenow={prepPercent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Visit preparation progress"
                  className="w-full h-2 rounded-full bg-[var(--cf-surface-3)] overflow-hidden"
                >
                  <div
                    className="h-full bg-emerald-600 dark:bg-emerald-400 rounded-full transition-all duration-300"
                    style={{ width: `${prepPercent}%` }}
                  />
                </div>

                {/* Checklist Preview */}
                <div className="space-y-2 pt-1">
                  {checklist.map((item) => (
                    <div
                      key={item.id}
                      role="checkbox"
                      tabIndex={0}
                      aria-checked={item.isDone}
                      onClick={() => handleToggleChecklist(item.id)}
                      onKeyDown={(e) => {
                        if (e.key === ' ' || e.key === 'Enter') {
                          e.preventDefault();
                          handleToggleChecklist(item.id);
                        }
                      }}
                      className="flex items-start gap-2.5 text-xs cursor-pointer select-none focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] p-1 rounded-lg hover:bg-[var(--cf-surface-3)] transition-colors"
                    >
                      <div
                        className={cn(
                          'w-4 h-4 rounded mt-0.5 flex items-center justify-center shrink-0 border transition-colors',
                          item.isDone
                            ? 'bg-emerald-600 border-emerald-600 text-white'
                            : 'border-[var(--cf-border-strong)] bg-[var(--cf-surface)]'
                        )}
                      >
                        {item.isDone && <Check className="w-3 h-3 stroke-[3]" />}
                      </div>
                      <span className={cn('flex-1 text-[var(--cf-fg)]', item.isDone && 'line-through text-[var(--cf-fg-muted)]')}>
                        {item.text}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Actions & Provenance */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    leftIcon={<MessageSquare className="w-4 h-4" />}
                    onClick={() => router.push(profilePath(profile.id, `chat?agent=${encodeURIComponent(appointment.specialistId || 'visit-steward')}`))}
                  >
                    Continue prep
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    leftIcon={<Printer className="w-4 h-4" />}
                    onClick={() => window.print()}
                  >
                    Print prep sheet
                  </Button>
                </div>

                {appointment.savedToNotesTimestamp && (
                  <span className="text-[11px] text-[var(--cf-fg-subtle)]">
                    {appointment.savedToNotesTimestamp}
                  </span>
                )}
              </div>
            </div>
          ) : (
            <EmptyState
              icon={<Calendar className="w-6 h-6 text-emerald-600" />}
              title="No upcoming visits scheduled"
              description="Add an appointment or ask Visit Steward to help prepare questions and documents for an upcoming doctor visit."
              action={{
                label: 'Prepare with Visit Steward',
                onClick: () => router.push(profilePath(profile.id, 'chat?agent=visit-steward'))
              }}
            />
          )}
        </section>

        {/* "Ask about [Person]" Hero Trigger Card */}
        <section
          aria-labelledby="section-ask"
          className="flex flex-col justify-between p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
        >
          <div className="flex items-center gap-2 pb-3 mb-4 border-b border-[var(--cf-border)]">
            <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            <h2 id="section-ask" className="text-base font-semibold text-[var(--cf-fg)]">
              Ask about {profile.name}
            </h2>
          </div>

          <form onSubmit={handleAskSubmit} className="space-y-3">
            <textarea
              aria-label={`Ask Carefold about ${profile.name}`}
              placeholder={`Ask anything about ${profile.name.split(' ')[0].toLowerCase()}'s health, paperwork, or visits...`}
              value={askDraft}
              onChange={(e) => setAskDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleAskSubmit();
                }
              }}
              className="w-full h-24 p-3 text-xs sm:text-sm rounded-xl border border-[var(--cf-border-strong)] bg-[var(--cf-surface)] text-[var(--cf-fg)] placeholder:text-[var(--cf-fg-subtle)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)] resize-none"
            />
            <div className="flex justify-end">
              <Button
                variant="primary"
                size="sm"
                type="submit"
                disabled={!askDraft.trim()}
              >
                Ask helper
              </Button>
            </div>
          </form>

          {/* Quick Starters */}
          <div className="space-y-2 mt-4 pt-3 border-t border-[var(--cf-border)]">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] block">
              Suggested starters
            </span>
            {[
              {
                label: 'Prepare for cardiologist visit',
                prompt: 'Prepare questions for cardiologist visit on Tuesday'
              },
              {
                label: 'Review recent bills',
                prompt: 'Review recent medical bills and insurance statements'
              },
              {
                label: 'Check medication schedule',
                prompt: 'Check current medication schedule and daily routines'
              }
            ].map((starter) => (
              <button
                key={starter.label}
                type="button"
                onClick={() => handleStarterClick(starter.prompt)}
                className="w-full flex items-center justify-between p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] hover:bg-[var(--cf-surface-3)] text-left text-xs text-[var(--cf-fg)] font-medium transition min-h-[44px]"
              >
                <span>{starter.label}</span>
                <ChevronRight className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0 ml-2" />
              </button>
            ))}
          </div>
        </section>
      </div>

      {/* 3. Secondary Three-Column Grid: Paperwork, Routines, Recent Notes */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Paperwork Card */}
        <section
          aria-labelledby="section-paperwork"
          className="flex flex-col justify-between p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
        >
          <div>
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-[var(--cf-border)]">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-sky-600 dark:text-sky-400" />
                <h2 id="section-paperwork" className="text-base font-semibold text-[var(--cf-fg)]">
                  Paperwork & coverage
                </h2>
              </div>
              {paperwork && (
                <Badge variant="warning">{paperwork.statusBadge}</Badge>
              )}
            </div>

            {paperwork ? (
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-[var(--cf-fg)]">
                    {paperwork.title}
                  </h3>
                  <span className="text-xs text-[var(--cf-fg-muted)]">Blue Shield Silver PPO</span>
                </div>
                <p className="text-xs text-[var(--cf-fg-muted)]">
                  {paperwork.facility}
                </p>

                {/* Financial KV Grid */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 p-3 rounded-xl bg-[var(--cf-surface-2)] text-xs border border-[var(--cf-border)] mt-2">
                  <div>
                    <span className="text-[10px] text-[var(--cf-fg-subtle)] block">Deductible</span>
                    <span className="font-semibold text-[var(--cf-fg)]">$450 / $1,500</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--cf-fg-subtle)] block">Copay</span>
                    <span className="font-semibold text-[var(--cf-fg)]">$35 Specialist</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-[var(--cf-fg-subtle)] block">You may owe</span>
                    <span className="font-bold text-amber-700 dark:text-amber-400">{paperwork.patientOwedAmount}</span>
                  </div>
                </div>
              </div>
            ) : (
              <EmptyState
                icon={<FileText className="w-6 h-6 text-sky-600" />}
                title="No insurance paperwork on file"
                description="Drop medical bills, explanation of benefits, or prior authorization letters into chat to extract structured summaries."
                action={{
                  label: 'Upload paperwork',
                  onClick: () => router.push(profilePath(profile.id, 'chat'))
                }}
              />
            )}
          </div>

          {paperwork && (
            <div className="pt-4 border-t border-[var(--cf-border)] mt-4">
              <Link
                href={profilePath(profile.id, `chat?prompt=${encodeURIComponent(`Review paperwork: ${paperwork.title}`)}`)}
                className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline inline-flex items-center gap-1 min-h-[36px]"
              >
                Review statement →
              </Link>
            </div>
          )}
        </section>

        {/* Routines Card */}
        <section
          aria-labelledby="section-routines"
          className="flex flex-col justify-between p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
        >
          <div>
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-[var(--cf-border)]">
              <div className="flex items-center gap-2">
                <Heart className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                <h2 id="section-routines" className="text-base font-semibold text-[var(--cf-fg)]">
                  Daily routines
                </h2>
              </div>
              <Link
                href={profilePath(profile.id, 'chat?agent=habit-companion')}
                className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline"
              >
                Log
              </Link>
            </div>

            {routines && routines.length > 0 ? (
              <div className="space-y-3">
                {routines.map((routine) => (
                  <div key={routine.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-medium text-[var(--cf-fg)] truncate flex-1">
                      {routine.name}
                    </span>

                    {/* 7-day dot progress indicators */}
                    <div className="flex items-center gap-1 shrink-0" aria-hidden="true">
                      {routine.daysCompleted.map((done, idx) => (
                        <div
                          key={idx}
                          className={cn(
                            'w-2.5 h-2.5 rounded-xs transition-colors',
                            done
                              ? 'bg-emerald-600 dark:bg-emerald-400'
                              : 'bg-[var(--cf-surface-3)]'
                          )}
                        />
                      ))}
                    </div>

                    <span className="text-[11px] text-[var(--cf-fg-subtle)] font-semibold w-6 text-right shrink-0">
                      {routine.summaryCount}
                    </span>
                  </div>
                ))}

                <p className="text-[11px] text-[var(--cf-fg-subtle)] mt-3 pt-2 border-t border-[var(--cf-border)]">
                  Tracking only — no judgement on readings.
                </p>
              </div>
            ) : (
              <EmptyState
                icon={<Activity className="w-6 h-6 text-emerald-600" />}
                title="No active daily routines"
                description="Ask Habit Companion to set up gentle daily habit check-ins and routine tracking."
                action={{
                  label: 'Set up routines',
                  onClick: () => router.push(profilePath(profile.id, 'chat?agent=habit-companion'))
                }}
              />
            )}
          </div>
        </section>

        {/* Recent Clinical Notes Card */}
        <section
          aria-labelledby="section-notes"
          className="flex flex-col justify-between p-6 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm"
        >
          <div>
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-[var(--cf-border)]">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                <h2 id="section-notes" className="text-base font-semibold text-[var(--cf-fg)]">
                  Recent notes
                </h2>
              </div>
              <Link
                href={profilePath(profile.id, 'library')}
                className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline"
              >
                Library
              </Link>
            </div>

            {notes && notes.length > 0 ? (
              <div className="space-y-3">
                {notes.map((note) => (
                  <Link
                    key={note.id}
                    href={profilePath(profile.id, 'library')}
                    className="block p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] hover:bg-[var(--cf-surface-3)] transition text-xs"
                  >
                    <div className="font-semibold text-[var(--cf-fg)] truncate">
                      {note.title}
                    </div>
                    <div className="text-[11px] text-[var(--cf-fg-subtle)] mt-0.5">
                      {note.authorAgentTitle} · {note.dateFormatted}
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={<BookOpen className="w-6 h-6 text-indigo-600" />}
                title="No notes for this person yet"
                description="Notes generated during consultations with clinical guides and stewards will appear here."
                action={{
                  label: 'Start a consultation',
                  onClick: () => router.push(profilePath(profile.id, 'chat'))
                }}
              />
            )}
          </div>

          {notes && notes.length > 0 && (
            <div className="pt-4 border-t border-[var(--cf-border)] mt-4">
              <Link
                href={profilePath(profile.id, 'library')}
                className="text-xs font-semibold text-[var(--cf-primary-hover)] hover:underline inline-flex items-center gap-1 min-h-[36px]"
              >
                View all notes in Library →
              </Link>
            </div>
          )}
        </section>
      </div>

      <ProfileEditModal
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        profile={profile as any}
        onSaved={(updated) => setProfileOverride(updated as any)}
      />
    </div>
  );
}
