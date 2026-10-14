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
    const res = await fetch(`${backendUrl}/api/v1/skills/${encodeURIComponent(cleanId)}`, {
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
