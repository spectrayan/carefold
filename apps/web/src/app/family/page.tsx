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

'use client';

import React, { useState, useEffect } from 'react';
import { UserCheck, Printer, CheckCircle2, Plus } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import {
  type CareProfile,
  type ViewerInvite,
  loadHouseholdProfiles,
  fetchHouseholdProfiles,
  fetchViewerInvites,
  revokeViewerInvite,
  HOUSEHOLD_PROFILES_CHANGED_EVENT
} from '@/lib/familyProfiles';
import {
  MemberCard,
  RoleMatrixTable,
  ViewerInviteModal,
  ShareBundleModal,
  ProfileEditModal,
  type ShareBundleRecord
} from '@/components/family';

export default function FamilyPage() {
  const [profiles, setProfiles] = useState<CareProfile[]>([]);
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [shareModalOpen, setShareModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<CareProfile | null>(null);

  // Active invitations
  const [invitations, setInvitations] = useState<ViewerInvite[]>([]);

  // Exported share bundles history
  const [shareBundles, setShareBundles] = useState<ShareBundleRecord[]>([]);

  useEffect(() => {
    let isMounted = true;

    // Immediate synchronous load from cache
    setProfiles(loadHouseholdProfiles());
    try {
      const storedInvites = localStorage.getItem('carefold_viewer_invitations');
      if (storedInvites) {
        const parsed = JSON.parse(storedInvites);
        if (Array.isArray(parsed)) setInvitations(parsed);
      }
    } catch {}

    // Background async refresh from backend API
    const syncWithBackend = async () => {
      try {
        const [remoteProfiles, remoteInvites] = await Promise.all([
          fetchHouseholdProfiles(),
          fetchViewerInvites()
        ]);
        if (isMounted) {
          if (remoteProfiles.length > 0) setProfiles(remoteProfiles);
          if (remoteInvites.length > 0) setInvitations(remoteInvites);
        }
      } catch {
        // Keep cached data
      }
    };

    syncWithBackend();

    const handleProfilesChanged = () => setProfiles(loadHouseholdProfiles());
    window.addEventListener(HOUSEHOLD_PROFILES_CHANGED_EVENT, handleProfilesChanged);

    try {
      const storedBundles = localStorage.getItem('carefold_share_bundles');
      if (storedBundles) {
        const parsed = JSON.parse(storedBundles);
        if (Array.isArray(parsed)) setShareBundles(parsed);
      }
    } catch {}

    return () => {
      isMounted = false;
      window.removeEventListener(HOUSEHOLD_PROFILES_CHANGED_EVENT, handleProfilesChanged);
    };
  }, []);

  const handleInviteCreated = (newInvite: ViewerInvite) => {
    setInvitations((prev) => {
      const next = [newInvite, ...prev.filter((i) => i.id !== newInvite.id)];
      try {
        const safeInvites = next.map((inv) => ({
          id: String(inv.id),
          inviteeName: String(inv.inviteeName),
          targetProfileId: String(inv.targetProfileId),
          targetProfileName: String(inv.targetProfileName),
          permissions: {
            view_clinical: Boolean(inv.permissions?.view_clinical),
            view_paperwork: Boolean(inv.permissions?.view_paperwork)
          },
          expiresInDays: Number(inv.expiresInDays) || 30,
          inviteCode: String(inv.inviteCode),
          createdAt: String(inv.createdAt)
        }));
        localStorage.setItem('carefold_viewer_invitations', JSON.stringify(safeInvites));
      } catch {}
      return next;
    });
  };

  const handleRevokeInvite = (id: string) => {
    const invite = invitations.find((i) => i.id === id);
    setInvitations((prev) => {
      const next = prev.filter((i) => i.id !== id);
      try {
        const safeInvites = next.map((inv) => ({
          id: String(inv.id),
          inviteeName: String(inv.inviteeName),
          targetProfileId: String(inv.targetProfileId),
          targetProfileName: String(inv.targetProfileName),
          permissions: {
            view_clinical: Boolean(inv.permissions?.view_clinical),
            view_paperwork: Boolean(inv.permissions?.view_paperwork)
          },
          expiresInDays: Number(inv.expiresInDays) || 30,
          inviteCode: String(inv.inviteCode),
          createdAt: String(inv.createdAt)
        }));
        localStorage.setItem('carefold_viewer_invitations', JSON.stringify(safeInvites));
      } catch {}
      return next;
    });
    if (invite) {
      revokeViewerInvite(invite.targetProfileId, invite.id).catch(() => {});
    }
  };

  const handleBundleExported = (newBundle: ShareBundleRecord) => {
    setShareBundles((prev) => {
      const next = [newBundle, ...prev];
      try {
        const safeBundles = next.map((b) => ({
          id: String(b.id),
          profileId: String(b.profileId),
          profileName: String(b.profileName),
          title: String(b.title),
          exportedAt: String(b.exportedAt)
        }));
        localStorage.setItem('carefold_share_bundles', JSON.stringify(safeBundles));
      } catch {}
      return next;
    });
  };

  return (
    <div className="max-w-7xl mx-auto px-3.5 sm:px-6 lg:px-8 py-4 sm:py-6 lg:py-8 space-y-8 sm:space-y-10">
      {/* Header Breadcrumbs & Action Cluster */}
      <div className="space-y-4">
        <nav aria-label="Breadcrumb" className="text-xs text-[var(--cf-fg-subtle)] flex items-center gap-1.5">
          <span>Household</span>
          <span>/</span>
          <span className="text-[var(--cf-fg)] font-medium">Family</span>
        </nav>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-[var(--cf-fg)] tracking-tight">
              Family
            </h1>
            <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1.5 max-w-2xl leading-relaxed">
              People you help care for on this computer. Each person&apos;s chats, documents and notes are kept separate.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-2.5">
            <Button
              variant="primary"
              size="sm"
              data-testid="add-member-btn"
              onClick={() =>
                setEditingProfile({
                  id: '',
                  name: '',
                  relationship: 'Family',
                  role: 'guardian',
                  colorSlot: (((profiles.length % 5) + 1) as any),
                  stats: { chats: 0, items: 0 }
                })
              }
            >
              <Plus className="w-4 h-4 mr-1.5" />
              Add member
            </Button>

            <Button
              variant="secondary"
              size="sm"
              data-testid="invite-viewer-btn"
              onClick={() => setInviteModalOpen(true)}
            >
              <UserCheck className="w-4 h-4 mr-1.5" />
              Invite a viewer
            </Button>

            <Button
              variant="secondary"
              size="sm"
              data-testid="export-bundle-btn"
              onClick={() => setShareModalOpen(true)}
            >
              <Printer className="w-4 h-4 mr-1.5" />
              Export share bundle
            </Button>
          </div>
        </div>
      </div>

      {/* Members Grid */}
      <section aria-labelledby="members-heading" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 id="members-heading" className="text-lg font-bold text-[var(--cf-fg)]">
            Household Members ({profiles.length})
          </h2>
        </div>

        <div
          data-testid="members-grid"
          className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-5"
        >
          {profiles.map((profile) => (
            <MemberCard
              key={profile.id}
              profile={profile}
              onEdit={(p) => setEditingProfile(p)}
            />
          ))}
        </div>
      </section>

      {/* Role Matrix Section ("Who can see what") */}
      <section aria-labelledby="role-matrix-heading">
        <RoleMatrixTable profiles={profiles} />
      </section>

      {/* Invitations and Shares Section */}
      <section aria-labelledby="invitations-shares-heading" className="space-y-4">
        <div className="p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm space-y-6">
          <div>
            <h2 id="invitations-shares-heading" className="text-base font-bold text-[var(--cf-fg)] tracking-tight">
              Invitations and shares
            </h2>
            <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
              Active local viewer invitations and printed care sheets. Viewers sign in on your local device or network.
            </p>
          </div>

          {/* Active Invitations List */}
          <div className="space-y-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] block">
              Active Viewers
            </span>

            {invitations.length === 0 ? (
              <p className="text-xs text-[var(--cf-fg-subtle)] italic">No active viewer invitations.</p>
            ) : (
              <div className="divide-y divide-[var(--cf-border)]" data-testid="invitations-list">
                {invitations.map((invite) => (
                  <div
                    key={invite.id}
                    data-testid={`invite-row-${invite.id}`}
                    className="py-3 flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-[var(--cf-fg)]">{invite.inviteeName}</span>
                        <span className="px-2 py-0.5 rounded text-[11px] bg-amber-500/10 text-amber-700 dark:text-amber-400">
                          Viewer &middot; {invite.targetProfileName}
                        </span>
                      </div>
                      <p className="text-[var(--cf-fg-subtle)]">
                        Code: <code className="font-mono bg-[var(--cf-surface-2)] px-1 rounded">{invite.inviteCode}</code> &middot;{' '}
                        {invite.permissions.view_clinical ? 'Visit prep & clinical' : ''}
                        {invite.permissions.view_clinical && invite.permissions.view_paperwork ? ', ' : ''}
                        {invite.permissions.view_paperwork ? 'Insurance & paperwork' : ''}
                      </p>
                    </div>

                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/20"
                      onClick={() => handleRevokeInvite(invite.id)}
                      data-testid={`revoke-invite-${invite.id}`}
                    >
                      Revoke
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Exported Share Bundles History */}
          <div className="space-y-3 pt-3 border-t border-[var(--cf-border)]">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] block">
              Recent Printed &amp; Exported Bundles
            </span>

            <div className="divide-y divide-[var(--cf-border)]" data-testid="bundles-list">
              {shareBundles.map((bundle) => (
                <div key={bundle.id} className="py-2.5 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 text-[var(--cf-fg)]">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                    <span>{bundle.title}</span>
                  </div>
                  <span className="text-[var(--cf-fg-subtle)]">{bundle.exportedAt}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Modals */}
      <ViewerInviteModal
        open={inviteModalOpen}
        onOpenChange={setInviteModalOpen}
        profiles={profiles}
        onInviteCreated={handleInviteCreated}
      />

      <ShareBundleModal
        open={shareModalOpen}
        onOpenChange={setShareModalOpen}
        profiles={profiles}
        onBundleExported={handleBundleExported}
      />

      {editingProfile && (
        <ProfileEditModal
          isOpen={Boolean(editingProfile)}
          onClose={() => setEditingProfile(null)}
          profile={editingProfile}
          onSaved={() => {
            setEditingProfile(null);
            setProfiles(loadHouseholdProfiles());
          }}
        />
      )}
    </div>
  );
}
