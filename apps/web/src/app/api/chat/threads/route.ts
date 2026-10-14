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

export async function GET(req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  let search = '';
  let threadId = '';

  if (req?.url) {
    try {
      const parsed = new URL(req.url, 'http://localhost:3000');
      search = parsed.search;
      threadId = (parsed.searchParams.get('thread_id') || parsed.searchParams.get('id') || '').trim();
    } catch {
      search = '';
    }
  }

  if (threadId && !/^[a-zA-Z0-9_\-]+$/.test(threadId)) {
    return NextResponse.json(
      {
        error: `Invalid thread ID "${threadId}". Must be an alphanumeric slug.`,
        code: 'INVALID_ID'
      },
      { status: 400 }
    );
  }

  try {
    const forwardHeaders: Record<string, string> = { Accept: 'application/json' };
    const incomingCookie = req.headers.get('cookie');
    if (incomingCookie) {
      forwardHeaders['cookie'] = incomingCookie;
    }
    const authHeader = req.headers.get('authorization');
    if (authHeader) {
      forwardHeaders['authorization'] = authHeader;
    }

    const res = await fetch(`${backendUrl}/api/v1/chat/threads${search}`, {
      method: 'GET',
      headers: forwardHeaders,
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err && Object.keys(err).length > 0
          ? err
          : { error: 'Failed to retrieve thread history' },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: 'Failed to connect to Carefold backend service',
        code: 'BACKEND_UNAVAILABLE',
        details: err?.message || 'Connection refused'
      },
      { status: 503 }
    );
  }
}

export async function DELETE(req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  let threadId = '';
  let search = '';

  if (req?.url) {
    try {
      const parsed = new URL(req.url, 'http://localhost:3000');
      search = parsed.search;
      threadId = (parsed.searchParams.get('thread_id') || parsed.searchParams.get('id') || '').trim();
    } catch {
      search = '';
    }
  }

  if (!threadId) {
    try {
      const body = await req.json().catch(() => ({}));
      threadId = (body.thread_id || body.threadId || body.id || '').trim();
    } catch {}
  }

  if (!threadId) {
    return NextResponse.json(
      { error: "Parameter 'thread_id' is required.", code: 'MISSING_THREAD_ID' },
      { status: 400 }
    );
  }

  if (!/^[a-zA-Z0-9_\-]+$/.test(threadId)) {
    return NextResponse.json(
      {
        error: `Invalid thread ID "${threadId}". Must be an alphanumeric slug.`,
        code: 'INVALID_ID'
      },
      { status: 400 }
    );
  }

  try {
    const forwardHeaders: Record<string, string> = { Accept: 'application/json' };
    const incomingCookie = req.headers.get('cookie');
    if (incomingCookie) {
      forwardHeaders['cookie'] = incomingCookie;
    }
    const authHeader = req.headers.get('authorization');
    if (authHeader) {
      forwardHeaders['authorization'] = authHeader;
    }

    const targetUrl = search.includes('thread_id=')
      ? `${backendUrl}/api/v1/chat/threads${search}`
      : `${backendUrl}/api/v1/chat/threads/${encodeURIComponent(threadId)}`;

    const res = await fetch(targetUrl, {
      method: 'DELETE',
      headers: forwardHeaders
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err && Object.keys(err).length > 0
          ? err
          : { error: `Failed to delete thread "${threadId}"` },
        { status: res.status }
      );
    }

    const data = await res.json().catch(() => ({ success: true, deleted: true }));
    return NextResponse.json(data, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: 'Failed to connect to Carefold backend service',
        code: 'BACKEND_UNAVAILABLE',
        details: err?.message || 'Connection refused'
      },
      { status: 503 }
    );
  }
}
