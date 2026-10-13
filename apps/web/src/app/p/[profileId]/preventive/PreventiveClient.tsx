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
import {
  ShieldCheck,
  RefreshCw,
  UploadCloud,
  GraduationCap,
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import {
  ScheduleSourceSelector,
  PreventiveChecklist,
} from '@/components/preventive';
import { ClinicalImportWizard } from '@/components/imports';
import { SchoolFormsPanel } from '@/components/school-forms';
import {
  fetchPreventiveItems,
  updatePreventiveStatus,
  updateScheduleSource,
  triggerPreventiveAction,
} from '@/lib/preventiveClient';
import {
  listSchoolForms,
  regenerateSchoolFormPrefill,
  deleteSchoolForm,
} from '@/lib/schoolFormsClient';
import type {
  PreventiveActionType,
  PreventiveItem,
  PreventiveStatus,
  ScheduleSource,
} from '@/types/preventive';
import type { SchoolFormItem } from '@/types/schoolForms';

export interface PreventiveClientProps {
  profileId: string;
}

export function PreventiveClient({ profileId }: PreventiveClientProps) {
  const [items, setItems] = useState<PreventiveItem[]>([]);
  const [scheduleSource, setScheduleSource] =
    useState<ScheduleSource>('aap_2026');
  const [schoolForms, setSchoolForms] = useState<SchoolFormItem[]>([]);
  const [guardianOnlyEnforced, setGuardianOnlyEnforced] =
    useState<boolean>(true);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    'preventive' | 'imports' | 'school_forms'
  >('preventive');

  const loadData = useCallback(async () => {
    setError(null);
    setIsLoading(true);
    try {
      const [prevRes, formsRes] = await Promise.all([
        fetchPreventiveItems(profileId),
        listSchoolForms(profileId).catch(() => ({
          forms: [],
          guardian_only_enforced: true,
        })),
      ]);
      setItems(prevRes.items || []);
      if (prevRes.schedule_source) {
        setScheduleSource(prevRes.schedule_source);
      }
      setSchoolForms(formsRes.forms || []);
      setGuardianOnlyEnforced(formsRes.guardian_only_enforced ?? true);
    } catch (err: any) {
      setError(err.message || 'Failed to load preventive care checklist.');
    } finally {
      setIsLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleScheduleChange = async (nextSource: ScheduleSource) => {
    setScheduleSource(nextSource);
    try {
      await updateScheduleSource(profileId, nextSource);
      const refreshed = await fetchPreventiveItems(profileId, {
        schedule_source: nextSource,
      });
      setItems(refreshed.items || []);
    } catch (err: any) {
      setError(err.message || 'Failed to update schedule source.');
    }
  };

  const handleUpdateStatus = async (
    ruleId: string,
    status: PreventiveStatus,
    notes?: string
  ) => {
    try {
      const updated = await updatePreventiveStatus(profileId, ruleId, {
        status,
        completed_at:
          status === 'completed' ? new Date().toISOString() : undefined,
        notes,
      });
      setItems((prev) =>
        prev.map((item) => (item.rule_id === ruleId ? updated : item))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to update status.');
    }
  };

  const handleTriggerAction = async (
    ruleId: string,
    actionType: PreventiveActionType
  ) => {
    try {
      const res = await triggerPreventiveAction(profileId, ruleId, actionType);
      setActionMessage(
        res.message ||
          (actionType === 'add_to_visit_prep'
            ? 'Added item to Visit Prep checklist.'
            : 'Created reminder for preventive item.')
      );
    } catch (err: any) {
      setError(err.message || 'Failed to trigger action.');
    }
  };

  const handleRegeneratePrefill = async (formId: string) => {
    try {
      const updated = await regenerateSchoolFormPrefill(profileId, formId);
      setSchoolForms((prev) =>
        prev.map((f) => (f.id === formId ? updated : f))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to refresh school form prefill.');
    }
  };

  const handleDeleteForm = async (formId: string) => {
    try {
      await deleteSchoolForm(profileId, formId);
      setSchoolForms((prev) => prev.filter((f) => f.id !== formId));
    } catch (err: any) {
      setError(err.message || 'Failed to delete school form.');
    }
  };

  return (
    <div
      data-testid="preventive-client-page"
      className="max-w-6xl mx-auto px-4 sm:px-6 py-6 space-y-6"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-600 text-white flex items-center justify-center shadow-sm">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--cf-fg)]">
              Preventive Care, Clinical Imports &amp; Pediatric Forms
            </h1>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Age- and sex-specific screenings, AAP 2026 / CDC immunisations, record staging, and school health forms
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={loadData}
            leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh
          </Button>
        </div>
      </div>

      {/* Section Navigation */}
      <div className="flex items-center gap-2 border-b border-[var(--cf-border)] pb-3">
        <Button
          size="sm"
          variant={activeTab === 'preventive' ? 'primary' : 'ghost'}
          data-testid="section-tab-preventive"
          leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
          onClick={() => setActiveTab('preventive')}
        >
          Preventive Checklist
        </Button>
        <Button
          size="sm"
          variant={activeTab === 'imports' ? 'primary' : 'ghost'}
          data-testid="section-tab-imports"
          leftIcon={<UploadCloud className="w-3.5 h-3.5" />}
          onClick={() => setActiveTab('imports')}
        >
          Clinical &amp; Wearable Import
        </Button>
        <Button
          size="sm"
          variant={activeTab === 'school_forms' ? 'primary' : 'ghost'}
          data-testid="section-tab-school-forms"
          leftIcon={<GraduationCap className="w-3.5 h-3.5" />}
          onClick={() => setActiveTab('school_forms')}
        >
          Pediatric School Forms
        </Button>
      </div>

      {error && (
        <div
          data-testid="preventive-client-error"
          className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-900/50 text-xs text-rose-700 dark:text-rose-300"
        >
          {error}
        </div>
      )}

      {actionMessage && (
        <div
          data-testid="preventive-action-toast"
          className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-900/50 text-xs text-emerald-800 dark:text-emerald-200"
        >
          {actionMessage}
        </div>
      )}

      {activeTab === 'preventive' && (
        <div className="space-y-5">
          <ScheduleSourceSelector
            value={scheduleSource}
            onChange={handleScheduleChange}
          />
          <PreventiveChecklist
            items={items}
            isLoading={isLoading}
            onUpdateStatus={handleUpdateStatus}
            onTriggerAction={handleTriggerAction}
          />
        </div>
      )}

      {activeTab === 'imports' && (
        <ClinicalImportWizard
          profileId={profileId}
          onImportCommitted={() => loadData()}
        />
      )}

      {activeTab === 'school_forms' && (
        <SchoolFormsPanel
          forms={schoolForms}
          guardianOnlyEnforced={guardianOnlyEnforced}
          onRegeneratePrefill={handleRegeneratePrefill}
          onDeleteForm={handleDeleteForm}
        />
      )}
    </div>
  );
}
