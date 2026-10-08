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

async function proxyAdminRequest(req: NextRequest, subpath: string): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const url = new URL(req.url);
  const targetUrl = `${backendUrl}/api/admin/${subpath}${url.search}`;

  const forwardHeaders = new Headers();
  const incomingCookie = req.headers.get('cookie');
  if (incomingCookie) {
    forwardHeaders.set('cookie', incomingCookie);
  }

  const contentType = req.headers.get('content-type');
  if (contentType) {
    forwardHeaders.set('content-type', contentType);
  }

  const authHeader = req.headers.get('authorization');
  if (authHeader) {
    forwardHeaders.set('authorization', authHeader);
  }

  forwardHeaders.set('accept', 'application/json');

  const method = req.method;
  let body: BodyInit | undefined = undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    try {
      body = await req.text();
    } catch {
      // Body empty or unreadable
    }
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method,
      headers: forwardHeaders,
      body,
      cache: 'no-store'
    });

    const resData = await backendRes.text();
    const responseHeaders = new Headers();

    const backendContentType = backendRes.headers.get('content-type');
    if (backendContentType) {
      responseHeaders.set('content-type', backendContentType);
    }

    if (typeof backendRes.headers.getSetCookie === 'function') {
      const setCookies = backendRes.headers.getSetCookie();
      for (const cookie of setCookies) {
        responseHeaders.append('set-cookie', cookie);
      }
    } else {
      const setCookie = backendRes.headers.get('set-cookie');
      if (setCookie) {
        responseHeaders.set('set-cookie', setCookie);
      }
    }

    return new NextResponse(resData, {
      status: backendRes.status,
      headers: responseHeaders
    });
  } catch (err: any) {
    return NextResponse.json(
      { error: `Admin backend unreachable: ${err.message}`, code: 'BACKEND_UNREACHABLE' },
      { status: 503 }
    );
  }
}

export async function GET(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return proxyAdminRequest(req, path.join('/'));
}

export async function POST(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return proxyAdminRequest(req, path.join('/'));
}

export async function PUT(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return proxyAdminRequest(req, path.join('/'));
}

export async function PATCH(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return proxyAdminRequest(req, path.join('/'));
}

export async function DELETE(req: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  return proxyAdminRequest(req, path.join('/'));
}
