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
import SkillDetailPage from '@/app/skills/[id]/page';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ skillId: string }>;
}

export default async function HelperSkillDetailPage({ params }: PageProps) {
  const { skillId } = await params;
  return <SkillDetailPage params={Promise.resolve({ id: skillId })} />;
}
