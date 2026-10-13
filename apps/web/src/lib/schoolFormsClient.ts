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
