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
    const targetUrl = `${backendUrl}/api/v1/audit?${query.toString()}`;
    const forwardHeaders: Record<string, string> = { Accept: 'application/json' };
    const cookie = req.headers.get('cookie');
    if (cookie) {
      forwardHeaders['cookie'] = cookie;
    }
    const authHeader = req.headers.get('authorization');
    if (authHeader) {
      forwardHeaders['authorization'] = authHeader;
    }

    const res = await fetch(targetUrl, {
      method: 'GET',
      headers: forwardHeaders,
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
