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

export async function GET(
  req: Request | NextRequest,
  context: { params: Promise<{ slug: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const rawSlug = (resolvedParams.slug || '').trim();

  // Reject path traversal, slashes, and null bytes immediately with HTTP 400
  if (
    rawSlug.includes('..') ||
    rawSlug.includes('/') ||
    rawSlug.includes('\\') ||
    rawSlug.includes('\0') ||
    rawSlug.includes(';') ||
    rawSlug.includes('%')
  ) {
    return NextResponse.json(
      { error: `Invalid note slug "${rawSlug}". Path traversal characters are not permitted.`, code: 'INVALID_SLUG' },
      { status: 400 }
    );
  }

  const cleanSlug = rawSlug.endsWith('.md') ? rawSlug.slice(0, -3) : rawSlug;

  // Validate slug format to ensure strictly alphanumeric with dashes and underscores
  if (!cleanSlug || !/^[a-zA-Z0-9_\-]+$/.test(cleanSlug)) {
    return NextResponse.json(
      { error: `Invalid note slug "${rawSlug}". Must be a valid alphanumeric slug.`, code: 'INVALID_SLUG' },
      { status: 400 }
    );
  }

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
