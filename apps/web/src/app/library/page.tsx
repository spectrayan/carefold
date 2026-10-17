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

import React from 'react';
import { cookies } from 'next/headers';
import { LibraryClient } from './LibraryClient';
import type { AttachmentItem, WorkspaceNoteSummary } from '@/types/api';

export const dynamic = 'force-dynamic';

async function getInitialLibraryData(): Promise<{
  attachments: AttachmentItem[];
  notes: WorkspaceNoteSummary[];
}> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const reqHeaders: Record<string, string> = { Accept: 'application/json' };
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore.toString();
    if (cookieHeader) {
      reqHeaders.Cookie = cookieHeader;
    }
  } catch {
    // Static or test context without request headers
  }

  const [attachmentsRes, notesRes] = await Promise.allSettled([
    fetch(`${backendUrl}/api/v1/attachments`, {
      headers: reqHeaders,
      cache: 'no-store'
    }),
    fetch(`${backendUrl}/api/v1/notes`, {
      headers: reqHeaders,
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

export default async function LibraryPage({ profileId }: { profileId?: string } = {}) {
  const { attachments, notes } = await getInitialLibraryData();
  return <LibraryClient initialAttachments={attachments} initialNotes={notes} profileId={profileId || 'me'} />;
}
