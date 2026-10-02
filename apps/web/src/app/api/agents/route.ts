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

export async function GET(req: Request | NextRequest): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const url = new URL(req.url);
  const singleId = url.searchParams.get('id');

  try {
    const parsedBackend = new URL(backendUrl);
    if (parsedBackend.protocol !== 'http:' && parsedBackend.protocol !== 'https:') {
      return NextResponse.json({ error: 'Invalid backend URL protocol' }, { status: 500 });
    }
    parsedBackend.username = '';
    parsedBackend.password = '';

    let targetUrl: URL;
    if (singleId) {
      if (!/^[a-zA-Z0-9_-]+$/.test(singleId)) {
        return NextResponse.json({ error: 'Invalid agent ID format' }, { status: 400 });
      }
      targetUrl = new URL(`/api/agents/${singleId}`, parsedBackend);
    } else {
      targetUrl = new URL('/api/agents', parsedBackend);
      url.searchParams.forEach((val, key) => {
        targetUrl.searchParams.set(key, val);
      });
    }

    const res = await fetch(targetUrl.toString(), {
      method: 'GET',
      headers: { Accept: 'application/json' },
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
