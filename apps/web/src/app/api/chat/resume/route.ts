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

export interface ChatResumeRequestBody {
  thread_id?: string;
  threadId?: string;
  approval_id?: string;
  approvalId?: string;
  decision?: 'approved' | 'rejected';
  edited_args?: Record<string, any>;
  editedArgs?: Record<string, any>;
  profile_id?: string;
  profileId?: string;
}

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({ status: 'ok', service: 'chat-resume' }, { status: 200 });
}

export async function POST(req: Request | NextRequest): Promise<Response> {
  // 1. Parse JSON payload
  let body: ChatResumeRequestBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON request payload.', code: 'INVALID_JSON' },
      { status: 400 }
    );
  }

  const threadId = body.thread_id || body.threadId;
  const approvalId = body.approval_id || body.approvalId;
  const decision = body.decision || 'approved';
  const editedArgs = body.edited_args !== undefined ? body.edited_args : body.editedArgs;
  const profileId = body.profile_id || body.profileId;

  // 2. Validate mandatory parameters
  if (!threadId || typeof threadId !== 'string' || !threadId.trim()) {
    return NextResponse.json(
      { error: 'Field "thread_id" is required and must be a non-empty string.', code: 'MISSING_THREAD_ID' },
      { status: 400 }
    );
  }

  if (!approvalId || typeof approvalId !== 'string' || !approvalId.trim()) {
    return NextResponse.json(
      { error: 'Field "approval_id" is required and must be a non-empty string.', code: 'MISSING_APPROVAL_ID' },
      { status: 400 }
    );
  }

  // 3. Resolve backend URL and prepare payload
  const backendUrl = process.env.BACKEND_URL || process.env.CAREFOLD_API_URL || 'http://127.0.0.1:8010';
  const targetUrl = `${backendUrl}/api/v1/chat/resume`;

  const payload: Record<string, any> = {
    thread_id: threadId.trim(),
    approval_id: approvalId.trim(),
    decision
  };
  if (editedArgs !== undefined) {
    payload.edited_args = editedArgs;
  }
  if (profileId) {
    payload.profile_id = typeof profileId === 'string' ? profileId.trim() : profileId;
  }

  // 4. Forward authentication and protocol headers
  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) forwardHeaders.set('cookie', incomingCookie);

  const authHeader = req.headers.get('authorization');
  if (authHeader) forwardHeaders.set('authorization', authHeader);

  const apiKey = req.headers.get('x-api-key');
  if (apiKey) forwardHeaders.set('x-api-key', apiKey);

  const provider = req.headers.get('x-provider');
  if (provider) forwardHeaders.set('x-provider', provider);

  const model = req.headers.get('x-model');
  if (model) forwardHeaders.set('x-model', model);

  forwardHeaders.set('content-type', 'application/json');
  forwardHeaders.set('accept', 'text/event-stream');

  // 5. Proxy to Python FastAPI backend
  try {
    const backendRes = await fetch(targetUrl, {
      method: 'POST',
      headers: forwardHeaders,
      body: JSON.stringify(payload),
      signal: req.signal
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text().catch(() => '');
      let parsedErr: any = null;
      try {
        parsedErr = JSON.parse(errText);
      } catch {}

      return NextResponse.json(
        parsedErr || { error: errText || `Backend responded with HTTP ${backendRes.status}` },
        { status: backendRes.status }
      );
    }

    if (!backendRes.body) {
      return NextResponse.json(
        { error: 'Backend response body was empty.', code: 'EMPTY_BACKEND_BODY' },
        { status: 502 }
      );
    }

    return new Response(backendRes.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no'
      }
    });
  } catch (err: any) {
    const isConnRefused =
      err.message?.includes('ECONNREFUSED') ||
      err.message?.includes('fetch failed') ||
      err.cause?.code === 'ECONNREFUSED';

    const errorMsg = isConnRefused
      ? `Carefold Python backend is unreachable at ${backendUrl}. Please start it with: pnpm dev:backend`
      : `Chat resume request failed: ${err.message}`;

    return NextResponse.json(
      { error: errorMsg, code: isConnRefused ? 'BACKEND_UNREACHABLE' : 'CHAT_RESUME_ERROR' },
      { status: 503 }
    );
  }
}
