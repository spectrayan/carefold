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

export async function POST(
  req: NextRequest,
  context: { params: Promise<{ approvalId: string }> }
): Promise<NextResponse> {
  const { approvalId } = await context.params;
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const targetUrl = `${backendUrl}/api/v1/approvals/${encodeURIComponent(approvalId)}/decide`;

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
  } catch {}

  try {
    const backendRes = await fetch(targetUrl, {
      method: 'POST',
      headers: forwardHeaders,
      body,
      cache: 'no-store'
    });

    const resData = await backendRes.text();
    const responseHeaders = new Headers();
    const contentType = backendRes.headers.get('content-type');
    if (contentType) responseHeaders.set('content-type', contentType);

    return new NextResponse(resData, {
      status: backendRes.status,
      headers: responseHeaders
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: `Carefold backend unreachable: ${err.message}`, code: 'BACKEND_UNREACHABLE' },
      { status: 503 }
    );
  }
}
