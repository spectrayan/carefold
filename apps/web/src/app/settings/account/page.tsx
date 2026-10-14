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
import { SecurityProfilePanel } from '@/components/settings/SecurityProfilePanel';

export default function AccountSettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-[var(--cf-fg)] tracking-tight">
          Account & Security
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          Manage your credentials, password complexity, and active device sessions.
        </p>
      </div>

      <div data-testid="settings-security-panel">
        <SecurityProfilePanel />
      </div>
    </div>
  );
}
