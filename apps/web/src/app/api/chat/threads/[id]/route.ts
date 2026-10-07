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
  _req: Request | NextRequest,
  context: { params: Promise<{ id: string }> | { id: string } }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const threadId = (resolvedParams.id || '').trim();

  // Validate slug to prevent path traversal
  if (!/^[a-zA-Z0-9_\-]+$/.test(threadId)) {
    return NextResponse.json(
      {
        error: `Invalid thread ID "${threadId}". Must be an alphanumeric slug.`,
        code: 'INVALID_ID'
      },
      { status: 400 }
    );
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const res = await fetch(`${backendUrl}/api/chat/threads/${threadId}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err && Object.keys(err).length > 0
          ? err
          : { error: `Thread "${threadId}" not found` },
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
