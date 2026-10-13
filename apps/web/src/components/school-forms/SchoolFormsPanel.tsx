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
  GraduationCap,
  ShieldCheck,
  Clock,
  Bell,
  Eye,
  Trash2,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import { SchoolFormPrefillSheet } from './SchoolFormPrefillSheet';
import type { SchoolFormItem } from '@/types/schoolForms';

export interface SchoolFormsPanelProps {
  forms: SchoolFormItem[];
  guardianOnlyEnforced?: boolean;
  onRegeneratePrefill?: (formId: string) => void | Promise<void>;
  onDeleteForm?: (formId: string) => void | Promise<void>;
  className?: string;
}

export function SchoolFormsPanel({
  forms = [],
  guardianOnlyEnforced = true,
  onRegeneratePrefill,
  onDeleteForm,
  className,
}: SchoolFormsPanelProps) {
  const [selectedFormId, setSelectedFormId] = useState<string | null>(
    forms[0]?.id ?? null
  );

  const selectedForm = forms.find((f) => f.id === selectedFormId) || null;

  const renderExpiryBadge = (form: SchoolFormItem) => {
    const days = form.days_until_expiry;
    if (days === undefined || days === null) {
      return form.expires_at ? (
        <Badge variant="neutral" size="sm">
          Expires {form.expires_at.slice(0, 10)}
        </Badge>
      ) : null;
    }
    if (days < 0) {
      return (
        <Badge
          data-testid={`school-form-expiry-${form.id}`}
          variant="danger"
          size="sm"
          dot
        >
          Expired ({Math.abs(days)}d ago)
        </Badge>
      );
    }
    if (days <= 30) {
      return (
        <Badge
          data-testid={`school-form-expiry-${form.id}`}
          variant="warning"
          size="sm"
          dot
        >
          Expires in {days} days
        </Badge>
      );
    }
    return (
      <Badge
        data-testid={`school-form-expiry-${form.id}`}
        variant="success"
        size="sm"
      >
        Valid ({days} days left)
      </Badge>
    );
  };

  return (
    <div data-testid="school-forms-panel" className={cn('space-y-4', className)}>
      <Card className="p-5 space-y-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-[var(--cf-border)]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-violet-600/10 text-violet-600 dark:text-violet-400 flex items-center justify-center shrink-0">
              <GraduationCap className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-[var(--cf-fg)]">
                Pediatric School &amp; Camp Health Forms
              </h3>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                Track annual physicals, sports clearances, and medication authorizations with prefill sheets
              </p>
            </div>
          </div>

          {guardianOnlyEnforced && (
            <Badge
              data-testid="under-13-guardian-safeguard-badge"
              variant="info"
              size="sm"
              icon={<ShieldCheck className="w-3.5 h-3.5" />}
            >
              Under-13 Guardian-Only Safeguard Active
            </Badge>
          )}
        </div>

        {forms.length === 0 ? (
          <div
            data-testid="school-forms-empty"
            className="py-8 text-center space-y-1"
          >
            <p className="text-sm font-semibold text-[var(--cf-fg)]">
              No school or camp health forms tracked yet
            </p>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Add a physical or immunisation form to generate a prefill sheet and renewal reminder.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5" data-testid="school-forms-list">
            {forms.map((form) => {
              const isSelected = selectedForm?.id === form.id;
              return (
                <div
                  key={form.id}
                  data-testid={`school-form-card-${form.id}`}
                  className={cn(
                    'p-3.5 rounded-xl border transition-colors flex flex-wrap items-center justify-between gap-3',
                    isSelected
                      ? 'border-violet-600 bg-violet-50/40 dark:bg-violet-950/20'
                      : 'border-[var(--cf-border)] bg-[var(--cf-surface)]'
                  )}
                >
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-bold text-[var(--cf-fg)]">
                        {form.title}
                      </span>
                      <span className="text-xs text-[var(--cf-fg-muted)]">
                        • {form.institution_name}
                      </span>
                      {renderExpiryBadge(form)}
                      {form.renewal_reminder_id && (
                        <span
                          data-testid={`school-form-reminder-badge-${form.id}`}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/50"
                        >
                          <Bell className="w-3 h-3" />
                          Renewal Reminder Set
                        </span>
                      )}
                      {form.guardian_only && (
                        <span
                          data-testid={`school-form-guardian-badge-${form.id}`}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-900/50"
                        >
                          <Clock className="w-3 h-3" />
                          Guardian Only
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-1.5">
                    <Button
                      size="sm"
                      variant={isSelected ? 'primary' : 'secondary'}
                      data-testid={`view-prefill-btn-${form.id}`}
                      leftIcon={<Eye className="w-3.5 h-3.5" />}
                      onClick={() =>
                        setSelectedFormId(isSelected ? null : form.id)
                      }
                    >
                      {isSelected ? 'Hide Prefill' : 'View Prefill Sheet'}
                    </Button>
                    {onDeleteForm && (
                      <Button
                        size="sm"
                        variant="ghost"
                        data-testid={`delete-school-form-${form.id}`}
                        leftIcon={<Trash2 className="w-3.5 h-3.5 text-rose-500" />}
                        onClick={() => onDeleteForm(form.id)}
                      >
                        Delete
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {selectedForm && (
        <SchoolFormPrefillSheet
          form={selectedForm}
          onRegeneratePrefill={onRegeneratePrefill}
          onClose={() => setSelectedFormId(null)}
        />
      )}
    </div>
  );
}
