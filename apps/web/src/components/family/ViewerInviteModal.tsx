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
import { Lock } from 'lucide-react';
import { type CareProfile, type ViewerInvite, createViewerInvite } from '@/lib/familyProfiles';

export type { ViewerInvite };

export interface ViewerInviteModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profiles: CareProfile[];
  onInviteCreated?: (invite: ViewerInvite) => void;
}

export function ViewerInviteModal({
  open,
  onOpenChange,
  profiles,
  onInviteCreated
}: ViewerInviteModalProps) {
  const [inviteeName, setInviteeName] = useState('');
  const [targetProfileId, setTargetProfileId] = useState(profiles[1]?.id || profiles[0]?.id || 'rosa');
  const [viewClinical, setViewClinical] = useState(true);
  const [viewPaperwork, setViewPaperwork] = useState(false);
  const [expiresInDays, setExpiresInDays] = useState(30);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteeName.trim()) return;

    const targetProfile = profiles.find((p) => p.id === targetProfileId);
    const targetProfileName = targetProfile ? targetProfile.name : targetProfileId;

    const randomBytes = new Uint8Array(4);
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      crypto.getRandomValues(randomBytes);
    }
    const hexCode = Array.from(randomBytes).map((b) => b.toString(16).padStart(2, '0')).join('').toUpperCase();

    const newInvite: ViewerInvite = {
      id: `inv-${Date.now()}`,
      inviteeName: inviteeName.trim(),
      targetProfileId,
      targetProfileName,
      permissions: {
        view_clinical: viewClinical,
        view_paperwork: viewPaperwork
      },
      expiresInDays,
      inviteCode: `cf-inv-${hexCode || 'LOCAL1'}`,
      createdAt: new Date().toISOString()
    };

    onInviteCreated?.(newInvite);
    setInviteeName('');
    onOpenChange(false);

    // Persist to relational database
    createViewerInvite(targetProfileId, {
      inviteeName: inviteeName.trim(),
      viewClinical,
      viewPaperwork,
      expiresInDays,
      targetProfileName
    }).catch(() => {});
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={handleSubmit} data-testid="viewer-invite-form">
          <DialogHeader>
            <DialogTitle>Invite a Viewer</DialogTitle>
            <DialogDescription>
              Grant a family member or trusted caregiver read-only access to a specific person&apos;s visit prep or paperwork.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4 text-sm">
            {/* Invitee Name */}
            <div className="space-y-1.5">
              <label htmlFor="invitee-name" className="text-xs font-semibold text-[var(--cf-fg)]">
                Invitee Name
              </label>
              <input
                id="invitee-name"
                data-testid="invitee-name-input"
                type="text"
                required
                placeholder="e.g. Dana Rivera"
                value={inviteeName}
                onChange={(e) => setInviteeName(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)]"
              />
            </div>

            {/* Target Profile Selection */}
            <div className="space-y-1.5">
              <label htmlFor="target-profile" className="text-xs font-semibold text-[var(--cf-fg)]">
                Person to grant access to
              </label>
              <select
                id="target-profile"
                data-testid="target-profile-select"
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

            {/* Granular Capabilities */}
            <div className="space-y-2 pt-1">
              <span className="text-xs font-semibold text-[var(--cf-fg)] block">
                Allowed Permissions
              </span>

              <label className="flex items-start gap-2.5 p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="permission-view-clinical"
                  checked={viewClinical}
                  onChange={(e) => setViewClinical(e.target.checked)}
                  className="mt-0.5 rounded text-emerald-600 focus:ring-emerald-500"
                />
                <div className="text-xs">
                  <span className="font-semibold text-[var(--cf-fg)] block">
                    View visit prep &amp; clinical summaries (view_clinical)
                  </span>
                  <span className="text-[var(--cf-fg-subtle)]">
                    Can see generated visit questions, checklists, and symptom notes.
                  </span>
                </div>
              </label>

              <label className="flex items-start gap-2.5 p-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] cursor-pointer">
                <input
                  type="checkbox"
                  data-testid="permission-view-paperwork"
                  checked={viewPaperwork}
                  onChange={(e) => setViewPaperwork(e.target.checked)}
                  className="mt-0.5 rounded text-emerald-600 focus:ring-emerald-500"
                />
                <div className="text-xs">
                  <span className="font-semibold text-[var(--cf-fg)] block">
                    View insurance &amp; billing dossiers (view_paperwork)
                  </span>
                  <span className="text-[var(--cf-fg-subtle)]">
                    Can see insurance summaries, appeals, and formulary guides.
                  </span>
                </div>
              </label>
            </div>

            {/* Expiration Period */}
            <div className="space-y-1.5">
              <label htmlFor="expiration-period" className="text-xs font-semibold text-[var(--cf-fg)]">
                Expiration
              </label>
              <select
                id="expiration-period"
                data-testid="expiration-select"
                value={expiresInDays}
                onChange={(e) => setExpiresInDays(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-xl bg-[var(--cf-surface)] border border-[var(--cf-border)] text-sm text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-[var(--cf-focus)]"
              >
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </div>

            {/* Local Security Reassurance */}
            <div className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-xs text-[var(--cf-fg-muted)] flex items-start gap-2">
              <Lock className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
              <span>
                Viewers sign in to Carefold on this computer or local network. Nothing is uploaded to any cloud server.
              </span>
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
              type="submit"
              variant="primary"
              size="sm"
              data-testid="submit-invite-btn"
              disabled={!inviteeName.trim()}
            >
              Generate local invite code
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
