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

import React from 'react';
import { notFound } from 'next/navigation';
import { SkillDetailClient } from './SkillDetailClient';
import type { SkillDetailResponse } from '@/types/api';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function SkillDetailPage({ params }: PageProps) {
  const { id } = await params;
  const cleanId = (id || '').trim();

  // Validate slug to prevent path traversal and reject templates
  if (
    !cleanId ||
    !/^[a-zA-Z0-9_\-]+$/.test(cleanId) ||
    cleanId.startsWith('_') ||
    cleanId.startsWith('.') ||
    cleanId === '_template'
  ) {
    return notFound();
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';

  try {
    const res = await fetch(`${backendUrl}/api/skills/${encodeURIComponent(cleanId)}`, {
      headers: { Accept: 'application/json' },
      cache: 'no-store'
    });

    if (!res.ok) {
      return notFound();
    }

    const data: SkillDetailResponse = await res.json();
    return <SkillDetailClient skill={data} />;
  } catch (err) {
    return notFound();
  }
}
