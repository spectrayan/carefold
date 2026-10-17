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
import type { ChatRequestBody } from '@/types/api';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(): Promise<NextResponse> {
  return NextResponse.json({ status: 'ok', service: 'chat' }, { status: 200 });
}

export async function POST(req: Request | NextRequest): Promise<Response> {
  // 1. Parse JSON body
  let body: ChatRequestBody;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: 'Invalid JSON request payload.', code: 'INVALID_JSON' },
      { status: 400 }
    );
  }

  const {
    agentId,
    profileId,
    profile_id,
    prompt,
    attachments,
    allow_clinical,
    provider,
    model,
    apiKey,
    customEndpoint,
    threadId,
    messages
  } = body;

  const rawAllowClinical: unknown =
    allow_clinical !== undefined
      ? allow_clinical
      : body.allowClinical;

  // Clinical consent is never assumed (#87): absent or non-true values mean no consent.
  const url = new URL(req.url);
  const allowClinicalQuery = url.searchParams.get('allow_clinical') ?? url.searchParams.get('allowClinical');
  const allowClinical =
    rawAllowClinical !== undefined
      ? rawAllowClinical === true || rawAllowClinical === 'true'
      : allowClinicalQuery === 'true' || allowClinicalQuery === '1';

  // 2. Validate required arguments
  if (!agentId || typeof agentId !== 'string') {
    return NextResponse.json(
      { error: 'Field "agentId" is required and must be a string.', code: 'MISSING_AGENT_ID' },
      { status: 400 }
    );
  }

  if (!prompt || typeof prompt !== 'string' || !prompt.trim()) {
    return NextResponse.json(
      { error: 'Field "prompt" is required and must be a non-empty string.', code: 'MISSING_PROMPT' },
      { status: 400 }
    );
  }

  // 3. Proxy to FastAPI Python backend (port 8010)
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const resolvedThreadId = threadId || `thread_${agentId}_${Date.now()}`;
  const resolvedProfileId =
    (typeof profile_id === 'string' && profile_id.trim()) ||
    (typeof profileId === 'string' && profileId.trim()) ||
    'me';

  const payload = {
    agent_id: agentId,
    agentId,
    profile_id: resolvedProfileId,
    profileId: resolvedProfileId,
    prompt: prompt.trim(),
    attachments: Array.isArray(attachments) ? attachments : [],
    messages: Array.isArray(messages) ? messages : [],
    allow_clinical: allowClinical,
    provider: provider || 'ollama',
    model,
    api_key: apiKey,
    apiKey,
    custom_endpoint: customEndpoint,
    customEndpoint,
    thread_id: resolvedThreadId,
    threadId: resolvedThreadId
  };

  const incomingCookie = req.headers.get('cookie');
  const authHeader = req.headers.get('authorization');
  try {
    const proxyHeaders = {
      'Content-Type': 'application/json',
      ...(incomingCookie ? { cookie: incomingCookie } : {}),
      ...(authHeader ? { authorization: authHeader } : {}),
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
      ...(provider ? { 'x-provider': provider } : {}),
      ...(model ? { 'x-model': model } : {})
    };

    let backendRes = await fetch(`${backendUrl}/api/v1/chat`, {
      method: 'POST',
      headers: proxyHeaders,
      body: JSON.stringify(payload),
      signal: req.signal
    });

    if (backendRes.status === 404) {
      const meRes = await fetch(`${backendUrl}/api/v1/profiles/me`, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
          ...(incomingCookie ? { cookie: incomingCookie } : {}),
          ...(authHeader ? { authorization: authHeader } : {})
        },
        signal: req.signal
      }).catch(() => null);

      if (meRes && meRes.ok) {
        const meProfile = await meRes.json().catch(() => null);
        if (meProfile && typeof meProfile.id === 'string' && meProfile.id !== resolvedProfileId) {
          const retryPayload = {
            ...payload,
            profile_id: meProfile.id,
            profileId: meProfile.id
          };
          backendRes = await fetch(`${backendUrl}/api/v1/chat`, {
            method: 'POST',
            headers: proxyHeaders,
            body: JSON.stringify(retryPayload),
            signal: req.signal
          });
        }
      }
    }

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
      : `Chat request failed: ${err.message}`;

    return NextResponse.json(
      { error: errorMsg, code: isConnRefused ? 'BACKEND_UNREACHABLE' : 'CHAT_ERROR' },
      { status: 503 }
    );
  }
}
