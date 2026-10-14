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
import type { AttachmentUploadResponse } from '@/types/api';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: Request | NextRequest
): Promise<NextResponse<AttachmentUploadResponse | { error: string; code?: string }>> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);
  const search = url.search;

  try {
    const formData = await req.formData();
    const file = formData.get('file');

    if (!file || !(file instanceof File)) {
      return NextResponse.json(
        { error: 'No file uploaded in form field "file".', code: 'MISSING_FILE' },
        { status: 400 }
      );
    }

    const forwardData = new FormData();
    forwardData.append('file', file, file.name);

    const incomingCookie = req.headers.get('cookie');
    const authHeader = req.headers.get('authorization');
    const headers: Record<string, string> = {};
    if (incomingCookie) headers['cookie'] = incomingCookie;
    if (authHeader) headers['authorization'] = authHeader;

    const res = await fetch(`${backendUrl}/api/v1/attachments${search}`, {
      method: 'POST',
      headers,
      body: forwardData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const errorMessage = err.detail || err.error || `Backend responded with HTTP ${res.status}`;
      return NextResponse.json(
        { error: errorMessage, code: err.code || 'UPLOAD_FAILED' },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json(
      { error: `Attachment upload failed: ${err.message}`, code: 'UPLOAD_FAILED' },
      { status: 500 }
    );
  }
}

export async function GET(req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);
  const search = url.search;

  const incomingCookie = req?.headers.get('cookie');
  const authHeader = req?.headers.get('authorization');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (incomingCookie) headers['cookie'] = incomingCookie;
  if (authHeader) headers['authorization'] = authHeader;

  try {
    const res = await fetch(`${backendUrl}/api/v1/attachments${search}`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err || { error: `Backend responded with HTTP ${res.status}` }, {
        status: res.status,
      });
    }

    const data = await res.json();
    return NextResponse.json(data, { status: 200 });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: `Carefold Python backend is unreachable at ${backendUrl}: ${err.message}`,
        code: 'BACKEND_UNREACHABLE',
      },
      { status: 503 }
    );
  }
}
