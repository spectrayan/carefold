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

function validateNoteSlug(rawSlug: string): { cleanSlug: string } | { error: string; status: number } {
  const trimmed = rawSlug.trim();
  if (
    trimmed.includes('..') ||
    trimmed.includes('/') ||
    trimmed.includes('\\') ||
    trimmed.includes('\0') ||
    trimmed.includes(';') ||
    trimmed.includes('%')
  ) {
    return {
      error: `Invalid note slug "${rawSlug}". Path traversal characters are not permitted.`,
      status: 400
    };
  }

  const cleanSlug = trimmed.endsWith('.md') ? trimmed.slice(0, -3) : trimmed;

  if (!cleanSlug || !/^[a-zA-Z0-9_\-]+$/.test(cleanSlug)) {
    return {
      error: `Invalid note slug "${rawSlug}". Must be a valid alphanumeric slug.`,
      status: 400
    };
  }

  return { cleanSlug };
}

export async function GET(
  req: Request | NextRequest,
  context: { params: Promise<{ slug: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const validation = validateNoteSlug(resolvedParams.slug || '');
  if ('error' in validation) {
    return NextResponse.json({ error: validation.error, code: 'INVALID_SLUG' }, { status: validation.status });
  }
  const cleanSlug = validation.cleanSlug;

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const targetUrl = `${backendUrl}/api/notes/${encodeURIComponent(cleanSlug)}`;
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers,
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err || { error: `Note "${cleanSlug}" not found.` },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: `Carefold Python backend is unreachable at ${backendUrl}. Please ensure it is running: ${err.message}`,
        code: 'BACKEND_UNREACHABLE'
      },
      { status: 503 }
    );
  }
}

export async function PUT(
  req: NextRequest,
  context: { params: Promise<{ slug: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const validation = validateNoteSlug(resolvedParams.slug || '');
  if ('error' in validation) {
    return NextResponse.json({ error: validation.error, code: 'INVALID_SLUG' }, { status: validation.status });
  }
  const cleanSlug = validation.cleanSlug;

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) forwardHeaders.set('cookie', incomingCookie);
  const authHeader = req.headers.get('authorization');
  if (authHeader) forwardHeaders.set('authorization', authHeader);
  forwardHeaders.set('content-type', 'application/json');
  forwardHeaders.set('accept', 'application/json');

  let body = '';
  try {
    body = await req.text();
  } catch {
    body = '{}';
  }

  try {
    const targetUrl = `${backendUrl}/api/notes/${encodeURIComponent(cleanSlug)}`;
    const res = await fetch(targetUrl, {
      method: 'PUT',
      headers: forwardHeaders,
      body,
      cache: 'no-store'
    });

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
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

export async function DELETE(
  req: NextRequest,
  context: { params: Promise<{ slug: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const validation = validateNoteSlug(resolvedParams.slug || '');
  if ('error' in validation) {
    return NextResponse.json({ error: validation.error, code: 'INVALID_SLUG' }, { status: validation.status });
  }
  const cleanSlug = validation.cleanSlug;

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) forwardHeaders.set('cookie', incomingCookie);
  const authHeader = req.headers.get('authorization');
  if (authHeader) forwardHeaders.set('authorization', authHeader);
  forwardHeaders.set('accept', 'application/json');

  try {
    const targetUrl = `${backendUrl}/api/notes/${encodeURIComponent(cleanSlug)}`;
    const res = await fetch(targetUrl, {
      method: 'DELETE',
      headers: forwardHeaders,
      cache: 'no-store'
    });

    const data = await res.json().catch(() => ({}));
    return NextResponse.json(data, { status: res.status });
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
