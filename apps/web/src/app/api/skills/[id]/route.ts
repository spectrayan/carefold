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

function validateSkillId(skillId: string): string | null {
  if (
    skillId.includes('..') ||
    skillId.includes('/') ||
    skillId.includes('\\') ||
    skillId.includes('\0') ||
    skillId.includes(' ') ||
    skillId.includes(';')
  ) {
    return 'Invalid skill ID. Must be an alphanumeric slug.';
  }

  if (skillId.startsWith('_') || skillId.startsWith('.') || skillId === '_template') {
    return 'Skill not found.';
  }

  if (!/^[a-zA-Z0-9_\-]+$/.test(skillId)) {
    return 'Invalid skill ID. Must be an alphanumeric slug.';
  }

  return null;
}

export async function GET(
  _req: Request | NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

  const valError = validateSkillId(skillId);
  if (valError) {
    const status = valError.includes('not found') ? 404 : 400;
    return NextResponse.json({ error: valError, code: status === 404 ? 'NOT_FOUND' : 'INVALID_ID' }, { status });
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

export async function PUT(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

  const valError = validateSkillId(skillId);
  if (valError) {
    const status = valError.includes('not found') ? 404 : 400;
    return NextResponse.json({ error: valError, code: status === 404 ? 'NOT_FOUND' : 'INVALID_ID' }, { status });
  }

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
    const targetUrl = `${backendUrl}/api/skills/${encodeURIComponent(skillId)}`;
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
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

  const valError = validateSkillId(skillId);
  if (valError) {
    const status = valError.includes('not found') ? 404 : 400;
    return NextResponse.json({ error: valError, code: status === 404 ? 'NOT_FOUND' : 'INVALID_ID' }, { status });
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) forwardHeaders.set('cookie', incomingCookie);
  const authHeader = req.headers.get('authorization');
  if (authHeader) forwardHeaders.set('authorization', authHeader);
  forwardHeaders.set('accept', 'application/json');

  try {
    const targetUrl = `${backendUrl}/api/skills/${encodeURIComponent(skillId)}`;
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
