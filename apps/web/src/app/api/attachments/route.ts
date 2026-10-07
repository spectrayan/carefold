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
import type { AttachmentUploadResponse } from '@/types/api';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(
  req: Request | NextRequest
): Promise<NextResponse<AttachmentUploadResponse | { error: string; code?: string }>> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

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

    const res = await fetch(`${backendUrl}/api/attachments`, {
      method: 'POST',
      body: forwardData
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

export async function GET(): Promise<NextResponse> {
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const res = await fetch(`${backendUrl}/api/attachments`, {
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
        error: `Carefold Python backend is unreachable at ${backendUrl}: ${err.message}`,
        code: 'BACKEND_UNREACHABLE'
      },
      { status: 503 }
    );
  }
}
