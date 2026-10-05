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

export async function GET(
  _req: Request | NextRequest,
  context: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  const resolvedParams = await context.params;
  const agentId = (resolvedParams.id || '').trim();

  // Validate slug to prevent path traversal
  if (!/^[a-zA-Z0-9_\-]+$/.test(agentId)) {
    return NextResponse.json(
      { error: `Invalid agent ID "${agentId}". Must be an alphanumeric slug.`, code: 'INVALID_ID' },
      { status: 400 }
    );
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  try {
    const url = new URL(_req.url);
    // Never assume clinical consent (#87): only an explicit client-side `true` is forwarded.
    const allowClinical = url.searchParams.get('allow_clinical') === 'true' ? 'true' : 'false';
    const res = await fetch(`${backendUrl}/api/agents/${agentId}?allow_clinical=${allowClinical}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return NextResponse.json(err || { error: `Agent "${agentId}" not found` }, {
        status: res.status
      });
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
