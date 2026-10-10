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

import React from 'react';
import { LibraryClient } from './LibraryClient';
import type { AttachmentItem, WorkspaceNoteSummary } from '@/types/api';

export const dynamic = 'force-dynamic';

async function getInitialLibraryData(): Promise<{
  attachments: AttachmentItem[];
  notes: WorkspaceNoteSummary[];
}> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const [attachmentsRes, notesRes] = await Promise.allSettled([
    fetch(`${backendUrl}/api/v1/attachments`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    }),
    fetch(`${backendUrl}/api/v1/notes`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    })
  ]);

  let attachments: AttachmentItem[] = [];
  if (attachmentsRes.status === 'fulfilled' && attachmentsRes.value.ok) {
    try {
      attachments = await attachmentsRes.value.json();
    } catch {
      attachments = [];
    }
  }

  let notes: WorkspaceNoteSummary[] = [];
  if (notesRes.status === 'fulfilled' && notesRes.value.ok) {
    try {
      notes = await notesRes.value.json();
    } catch {
      notes = [];
    }
  }

  return { attachments, notes };
}

export default async function LibraryPage() {
  const { attachments, notes } = await getInitialLibraryData();
  return <LibraryClient initialAttachments={attachments} initialNotes={notes} />;
}
