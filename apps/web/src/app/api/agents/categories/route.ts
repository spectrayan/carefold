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

export async function GET(_req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const parsedBackend = new URL(backendUrl);
    if (parsedBackend.protocol !== 'http:' && parsedBackend.protocol !== 'https:') {
      return NextResponse.json({ error: 'Invalid backend URL protocol' }, { status: 500 });
    }
    parsedBackend.username = '';
    parsedBackend.password = '';

    const targetUrl = new URL('/api/v1/agents/categories', parsedBackend);

    const clientUrl = new URL(_req.url);
    const domain = clientUrl.searchParams.get('domain');
    if (domain) {
      targetUrl.searchParams.set('domain', domain.replace(/[^a-zA-Z0-9_\-]/g, ''));
    }
    const depth = clientUrl.searchParams.get('depth');
    if (depth) {
      targetUrl.searchParams.set('depth', depth.replace(/[^0-9]/g, ''));
    }

    const headers: Record<string, string> = { Accept: 'application/json' };
    const incomingCookie = _req.headers.get('cookie');
    if (incomingCookie) headers['cookie'] = incomingCookie;
    const authHeader = _req.headers.get('authorization');
    if (authHeader) headers['authorization'] = authHeader;

    const res = await fetch(targetUrl.toString(), {
      method: 'GET',
      headers,
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err || { error: `Backend responded with HTTP ${res.status}` }, {
        status: res.status
      });
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
