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
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const targetUrl = `${backendUrl}/api/skills/${encodeURIComponent(skillId)}/docs`;
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers,
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

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const skillId = (resolvedParams.id || '').trim();

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
    const targetUrl = `${backendUrl}/api/skills/${encodeURIComponent(skillId)}/docs`;
    const res = await fetch(targetUrl, {
      method: 'POST',
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
