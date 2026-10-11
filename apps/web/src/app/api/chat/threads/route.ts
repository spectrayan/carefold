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
