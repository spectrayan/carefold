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

import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MIN_AUDIT_LIMIT = 1;
const MAX_AUDIT_LIMIT = 1000;
const DEFAULT_AUDIT_LIMIT = 50;

export async function GET(req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);

  // 1. Clamp limit client-side to bounds [1, 1000], defaulting to 50
  let limit = DEFAULT_AUDIT_LIMIT;
  const limitParam = url.searchParams.get('limit');
  if (limitParam !== null) {
    const parsed = Number(limitParam);
    if (!isNaN(parsed)) {
      limit = Math.min(Math.max(MIN_AUDIT_LIMIT, Math.floor(parsed)), MAX_AUDIT_LIMIT);
    }
  }

  // 2. Forward ONLY limit, agent_id, and event with full=false
  const query = new URLSearchParams();
  query.set('limit', String(limit));
  query.set('full', 'false');

  const agentId = url.searchParams.get('agent_id');
  if (agentId && agentId.trim()) {
    query.set('agent_id', agentId.trim());
  }

  const event = url.searchParams.get('event');
  if (event && event.trim()) {
    query.set('event', event.trim());
  }

  try {
    const targetUrl = `${backendUrl}/api/audit?${query.toString()}`;
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err || { error: `Backend responded with HTTP ${res.status}` }, {
        status: res.status
      });
    }

    const data = await res.json();

    // STRICT INVARIANT: Redacted mode only. Strip any accidental prompt or completion keys
    if (data && Array.isArray(data.events)) {
      data.events = data.events.map((ev: any) => {
        if (ev && typeof ev === 'object') {
          delete ev.prompt;
          delete ev.completion;
        }
        return ev;
      });
    }

    return NextResponse.json(data, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: `Carefold Python backend is unreachable at ${backendUrl}: ${err.message}`,
        code: 'BACKEND_UNREACHABLE'
      },
      { status: 503 }
    );
  }
}
