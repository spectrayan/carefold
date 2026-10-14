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

import type { SchoolFormItem, SchoolFormType } from '@/types/schoolForms';

export async function listSchoolForms(
  profileId: string
): Promise<{ forms: SchoolFormItem[]; guardian_only_enforced?: boolean }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-forms`,
    {
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to list school forms (${res.status})`);
  }
  return res.json();
}

export async function createSchoolForm(
  profileId: string,
  payload: {
    title: string;
    institution_name: string;
    form_type: SchoolFormType;
    issued_date?: string | null;
    expires_at?: string | null;
    notes?: string | null;
    create_renewal_reminder?: boolean;
  }
): Promise<SchoolFormItem> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-forms`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create school form (${res.status})`);
  }
  return res.json();
}

export async function regenerateSchoolFormPrefill(
  profileId: string,
  formId: string
): Promise<SchoolFormItem> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-forms/${encodeURIComponent(formId)}/prefill`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to regenerate school form prefill (${res.status})`
    );
  }
  return res.json();
}

export async function deleteSchoolForm(
  profileId: string,
  formId: string
): Promise<{ deleted: boolean; id: string }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/school-forms/${encodeURIComponent(formId)}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to delete school form (${res.status})`);
  }
  return res.json();
}
