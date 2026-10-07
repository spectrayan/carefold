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
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

  // Reject explicit path traversal, slashes, and null bytes immediately with HTTP 400
  if (
    skillId.includes('..') ||
    skillId.includes('/') ||
    skillId.includes('\\') ||
    skillId.includes('\0') ||
    skillId.includes(' ') ||
    skillId.includes(';')
  ) {
    return NextResponse.json(
      { error: `Invalid skill ID "${skillId}". Must be an alphanumeric slug.`, code: 'INVALID_ID' },
      { status: 400 }
    );
  }

  // Defensively reject template or private/hidden folders with HTTP 404
  if (skillId.startsWith('_') || skillId.startsWith('.') || skillId === '_template') {
    return NextResponse.json(
      { error: `Skill "${skillId}" not found.`, code: 'NOT_FOUND' },
      { status: 404 }
    );
  }

  // Validate slug format to ensure strictly alphanumeric with dashes/underscores
  if (!/^[a-zA-Z0-9_\-]+$/.test(skillId)) {
    return NextResponse.json(
      { error: `Invalid skill ID "${skillId}". Must be an alphanumeric slug.`, code: 'INVALID_ID' },
      { status: 400 }
    );
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const targetUrl = `${backendUrl}/api/skills/${encodeURIComponent(skillId)}`;
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err || { error: `Skill "${skillId}" not found.` },
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
