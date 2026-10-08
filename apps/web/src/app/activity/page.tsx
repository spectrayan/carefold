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
import { ActivityClient } from './ActivityClient';
import type { AuditEvent } from '@/types/api';

export const dynamic = 'force-dynamic';

async function getInitialAuditEvents(): Promise<AuditEvent[]> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const res = await fetch(`${backendUrl}/api/audit?limit=100&full=false`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data.events)) {
        return data.events.map((ev: any) => {
          if (ev && typeof ev === 'object') {
            delete ev.prompt;
            delete ev.completion;
          }
          return ev;
        });
      }
    }
  } catch {
    // Return empty list safely if backend is offline during SSR
  }

  return [];
}

export default async function ActivityPage() {
  const events = await getInitialAuditEvents();
  return <ActivityClient initialEvents={events} />;
}
