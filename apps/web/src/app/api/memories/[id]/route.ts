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

function validateKey(key: string): boolean {
  if (!key || !key.trim()) return false;
  // Reject path traversal, slashes, null bytes, command chars
  if (
    key.includes('..') ||
    key.includes('/') ||
    key.includes('\\') ||
    key.includes('\0') ||
    key.includes(';') ||
    key.includes('%')
  ) {
    return false;
  }
  return true;
}

export async function GET(
  req: Request | NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolved = await context.params;
  const rawKey = (resolved.id || '').trim();

  if (!validateKey(rawKey)) {
    return NextResponse.json(
      { error: `Invalid memory key "${rawKey}". Path traversal and control characters are prohibited.`, code: 'INVALID_KEY' },
      { status: 400 }
    );
  }

  const url = new URL(req.url);
  const namespace = url.searchParams.get('namespace')?.trim() || 'default';
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const targetUrl = `${backendUrl}/api/v1/memory/${encodeURIComponent(rawKey)}?namespace=${encodeURIComponent(namespace)}`;
    const res = await fetch(targetUrl, {
      method: 'GET',
      headers,
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err || { error: `Memory "${rawKey}" not found.` },
        { status: res.status }
      );
    }

    const data = await res.json();
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

export async function PUT(
  req: Request | NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolved = await context.params;
  const rawKey = (resolved.id || '').trim();

  if (!validateKey(rawKey)) {
    return NextResponse.json(
      { error: `Invalid memory key "${rawKey}". Path traversal and control characters are prohibited.`, code: 'INVALID_KEY' },
      { status: 400 }
    );
  }

  const body = await req.json().catch(() => null);
  if (!body || body.value === undefined) {
    return NextResponse.json({ error: 'Payload must contain a "value" field.', code: 'INVALID_PAYLOAD' }, { status: 400 });
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);
  const namespace = body.namespace || url.searchParams.get('namespace')?.trim() || 'default';

  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const targetUrl = `${backendUrl}/api/v1/memory/${encodeURIComponent(rawKey)}?namespace=${encodeURIComponent(namespace)}`;
    const res = await fetch(targetUrl, {
      method: 'PUT',
      headers,
      body: JSON.stringify(body),
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err || { error: `Failed to update memory "${rawKey}".` }, { status: res.status });
    }

    const data = await res.json();
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

export async function DELETE(
  req: Request | NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolved = await context.params;
  const rawKey = (resolved.id || '').trim();

  if (!validateKey(rawKey)) {
    return NextResponse.json(
      { error: `Invalid memory key "${rawKey}". Path traversal and control characters are prohibited.`, code: 'INVALID_KEY' },
      { status: 400 }
    );
  }

  const url = new URL(req.url);
  const namespace = url.searchParams.get('namespace')?.trim() || 'default';
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const targetUrl = `${backendUrl}/api/v1/memory/${encodeURIComponent(rawKey)}?namespace=${encodeURIComponent(namespace)}`;
    const res = await fetch(targetUrl, {
      method: 'DELETE',
      headers,
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(
        err || { error: `Failed to delete memory "${rawKey}".` },
        { status: res.status }
      );
    }

    const data = await res.json();
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
