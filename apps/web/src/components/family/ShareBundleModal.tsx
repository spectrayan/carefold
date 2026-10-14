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

import React, { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter
} from '@/components/ui/Dialog';
import { Button } from '@/components/ui/Button';
import { Printer } from 'lucide-react';
import type { CareProfile } from '@/lib/familyProfiles';

export interface ShareBundleRecord {
  id: string;
  profileId: string;
  profileName: string;
  title: string;
  exportedAt: string;
}

export interface ShareBundleModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profiles: CareProfile[];
  onBundleExported?: (record: ShareBundleRecord) => void;
}

export function ShareBundleModal({
  open,
  onOpenChange,
  profiles,
  onBundleExported
}: ShareBundleModalProps) {
  const [targetProfileId, setTargetProfileId] = useState(profiles[1]?.id || profiles[0]?.id || 'rosa');
  const [includePrep, setIncludePrep] = useState(true);
  const [includeMeds, setIncludeMeds] = useState(true);
  const [includeNotes, setIncludeNotes] = useState(false);

  const handleExport = () => {
    const profile = profiles.find((p) => p.id === targetProfileId) || profiles[0];
    const profileName = profile ? profile.name : 'Family member';

    const record: ShareBundleRecord = {
      id: `bundle-${Date.now()}`,
      profileId: targetProfileId,
      profileName,
      title: `${profileName}'s visit prep packet`,
      exportedAt: new Date().toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    };

    onBundleExported?.(record);
    onOpenChange(false);

    if (typeof window !== 'undefined' && typeof window.print === 'function') {
      try {
        window.print();
      } catch {
        // In testing environments or restricted frames
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <div data-testid="share-bundle-modal">
          <DialogHeader>
            <DialogTitle>Export Care Share Bundle</DialogTitle>
            <DialogDescription>
              Compile clean, printable clinical prep sheets and notes to take to the doctor&apos;s office or hand to a caregiver.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4 text-sm">
            {/* Target Profile Selection */}
            <div className="space-y-1.5">
              <label htmlFor="bundle-profile" className="text-xs font-semibold text-[var(--cf-fg)]">
                Person
              </label>
              <select
                id="bundle-profile"
                data-testid="bundle-profile-select"
                value={targetProfileId}
                onChange={(e) => setTargetProfileId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)]"
              >
                {profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.relationship})
                  </option>
                ))}
              </select>
            </div>

            {/* Sections to include */}
            <div className="space-y-2 pt-1">
              <span className="text-xs font-semibold text-[var(--cf-fg)] block">
                Sections to include
              </span>

              <label className="flex items-center gap-2.5 p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="bundle-section-prep"
                  checked={includePrep}
                  onChange={(e) => setIncludePrep(e.target.checked)}
                  className="rounded text-emerald-600 focus:ring-emerald-500"
                />
                <span className="text-xs font-medium text-[var(--cf-fg)]">
                  Upcoming Visit Prep Checklist &amp; Questions
                </span>
              </label>

              <label className="flex items-center gap-2.5 p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="bundle-section-meds"
                  checked={includeMeds}
                  onChange={(e) => setIncludeMeds(e.target.checked)}
                  className="rounded text-emerald-600 focus:ring-emerald-500"
                />
                <span className="text-xs font-medium text-[var(--cf-fg)]">
                  Active Medications, Allergies &amp; Vitals
                </span>
              </label>

              <label className="flex items-center gap-2.5 p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="bundle-section-notes"
                  checked={includeNotes}
                  onChange={(e) => setIncludeNotes(e.target.checked)}
                  className="rounded text-emerald-600 focus:ring-emerald-500"
                />
                <span className="text-xs font-medium text-[var(--cf-fg)]">
                  Recent Clinical Summaries &amp; Notes
                </span>
              </label>
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              data-testid="confirm-export-bundle-btn"
              onClick={handleExport}
            >
              <Printer className="w-3.5 h-3.5 mr-1" />
              Export &amp; Print Dossier
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
