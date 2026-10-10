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
