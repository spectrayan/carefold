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

export async function GET(
  req: Request | NextRequest,
  context: { params: Promise<{ id: string; doc: string }> }
): Promise<NextResponse> {
  const { id: skillId, doc } = await context.params;

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  const url = new URL(req.url);
  try {
    const targetUrl = `${backendUrl}/api/v1/skills/${encodeURIComponent(skillId)}/docs/${encodeURIComponent(doc)}${url.search}`;
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

export async function PUT(
  req: NextRequest,
  context: { params: Promise<{ id: string; doc: string }> }
): Promise<NextResponse> {
  const { id: skillId, doc } = await context.params;

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

  const url = new URL(req.url);
  try {
    const targetUrl = `${backendUrl}/api/v1/skills/${encodeURIComponent(skillId)}/docs/${encodeURIComponent(doc)}${url.search}`;
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
  context: { params: Promise<{ id: string; doc: string }> }
): Promise<NextResponse> {
  const { id: skillId, doc } = await context.params;

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) forwardHeaders.set('cookie', incomingCookie);
  const authHeader = req.headers.get('authorization');
  if (authHeader) forwardHeaders.set('authorization', authHeader);
  forwardHeaders.set('accept', 'application/json');

  const url = new URL(req.url);
  try {
    const targetUrl = `${backendUrl}/api/v1/skills/${encodeURIComponent(skillId)}/docs/${encodeURIComponent(doc)}${url.search}`;
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
