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
import { cookies, headers } from 'next/headers';
import { ActivityClient } from './ActivityClient';
import type { AuditEvent } from '@/types/api';

export const dynamic = 'force-dynamic';

interface InitialAuditResult {
  events: AuditEvent[];
  unauthenticated: boolean;
}

async function getInitialAuditEvents(): Promise<InitialAuditResult> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const cookieStore = await cookies();
    const headersList = await headers();

    const forwardHeaders: Record<string, string> = { Accept: 'application/json' };
    const cookieHeader = cookieStore.toString();
    if (cookieHeader) {
      forwardHeaders['cookie'] = cookieHeader;
    }
    const authHeader = headersList.get('authorization');
    if (authHeader) {
      forwardHeaders['authorization'] = authHeader;
    }

    const res = await fetch(`${backendUrl}/api/v1/audit?limit=100&full=false`, {
      headers: forwardHeaders,
      cache: 'no-store'
    });

    if (res.status === 401) {
      return { events: [], unauthenticated: true };
    }

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.events)) {
        const events = data.events.map((ev: any) => {
          if (ev && typeof ev === 'object') {
            delete ev.prompt;
            delete ev.completion;
          }
          return ev;
        });
        return { events, unauthenticated: false };
      }
    }
  } catch {
    // Return empty list safely if backend is offline during SSR
  }

  return { events: [], unauthenticated: false };
}

export default async function ActivityPage() {
  const { events, unauthenticated } = await getInitialAuditEvents();
  return <ActivityClient initialEvents={events} initialUnauthenticated={unauthenticated} />;
}
