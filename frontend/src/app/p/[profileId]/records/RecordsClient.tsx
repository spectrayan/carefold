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

'use client';

import React from 'react';
import { EhrChartWorkspace } from '@/health-ui/chart/EhrChartWorkspace';

export interface RecordsClientProps {
  profileId: string;
}

export function RecordsClient({ profileId }: RecordsClientProps) {
  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <EhrChartWorkspace profileId={profileId} />
    </div>
  );
}
