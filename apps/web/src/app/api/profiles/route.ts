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

function getForwardHeaders(req: Request | NextRequest): Headers {
  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) {
    forwardHeaders.set('cookie', incomingCookie);
  }

  const authHeader = req.headers.get('authorization');
  if (authHeader) {
    forwardHeaders.set('authorization', authHeader);
  }

  const contentType = req.headers.get('content-type');
  if (contentType) {
    forwardHeaders.set('content-type', contentType);
  }

  forwardHeaders.set('accept', 'application/json');
  return forwardHeaders;
}

export async function GET(req: NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);
  const targetUrl = `${backendUrl}/api/v1/profiles${url.search}`;
  const headers = getForwardHeaders(req);

  try {
    const backendRes = await fetch(targetUrl, {
      method: 'GET',
      headers,
      cache: 'no-store'
    });

    const resData = await backendRes.text();
    const responseHeaders = new Headers();
    const backendContentType = backendRes.headers.get('content-type');
    if (backendContentType) {
      responseHeaders.set('content-type', backendContentType);
    }

    if (typeof backendRes.headers.getSetCookie === 'function') {
      for (const cookie of backendRes.headers.getSetCookie()) {
        responseHeaders.append('set-cookie', cookie);
      }
    } else {
      const setCookie = backendRes.headers.get('set-cookie');
      if (setCookie) responseHeaders.set('set-cookie', setCookie);
    }

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

export async function POST(req: NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const targetUrl = `${backendUrl}/api/v1/profiles`;
  const headers = getForwardHeaders(req);

  let body: string | undefined = undefined;
  try {
    body = await req.text();
  } catch {
    body = '{}';
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method: 'POST',
      headers,
      body,
      cache: 'no-store'
    });

    const resData = await backendRes.text();
    const responseHeaders = new Headers();
    const backendContentType = backendRes.headers.get('content-type');
    if (backendContentType) {
      responseHeaders.set('content-type', backendContentType);
    }

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
