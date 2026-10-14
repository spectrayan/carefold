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

import React, { useState, useEffect } from 'react';
import { UserCheck, Printer, Plus, Eye, Key, Info } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Avatar } from '@/components/ui/Avatar';
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
import { useI18n } from '@/i18n';

export default function FamilyPage() {
  const { t } = useI18n();
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
    <div className="space-y-6">
      {/* Header Breadcrumbs & Action Cluster */}
      <div className="space-y-4">
        <nav aria-label="Breadcrumb" className="text-xs text-[var(--cf-fg-subtle)] flex items-center gap-1.5">
          <span>{t('family.breadcrumb_household')}</span>
          <span>/</span>
          <span className="text-[var(--cf-fg)] font-medium">{t('family.title')}</span>
        </nav>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-[var(--cf-fg)] tracking-tight">
              {t('family.title')}
            </h1>
            <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1.5 max-w-2xl leading-relaxed">
              {t('family.subtitle')}
            </p>
          </div>

          <div className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center gap-2.5">
            <Button
              variant="primary"
              size="sm"
              leftIcon={<Plus className="w-4 h-4 shrink-0" />}
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
              {t('family.add_member')}
            </Button>

            <Button
              variant="secondary"
              size="sm"
              leftIcon={<UserCheck className="w-4 h-4 shrink-0" />}
              data-testid="invite-viewer-btn"
              onClick={() => setInviteModalOpen(true)}
            >
              {t('family.invite_viewer')}
            </Button>

            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Printer className="w-4 h-4 shrink-0" />}
              data-testid="export-bundle-btn"
              onClick={() => setShareModalOpen(true)}
            >
              {t('family.export_bundle')}
            </Button>
          </div>
        </div>
      </div>

      {/* Members Grid */}
      <section aria-labelledby="members-heading" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 id="members-heading" className="text-lg font-bold text-[var(--cf-fg)]">
            {t('family.household_members', { count: profiles.length })}
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
              {t('family.invitations_shares')}
            </h2>
            <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
              {t('family.invitations_subtitle')}
            </p>
          </div>

          {/* Active Invitations List */}
          <div className="space-y-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] block">
              {t('family.active_viewers')}
            </span>

            {invitations.length === 0 ? (
              <p className="text-xs text-[var(--cf-fg-subtle)] italic">{t('family.no_active_viewers')}</p>
            ) : (
              <div className="divide-y divide-[var(--cf-border)]" data-testid="invitations-list">
                {invitations.map((invite) => (
                  <div
                    key={invite.id}
                    data-testid={`invite-row-${invite.id}`}
                    className="py-3 flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <Avatar name={invite.inviteeName} size="xs" colorSlot={5} />
                      <div className="space-y-0.5 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-[var(--cf-fg)]">{invite.inviteeName}</span>
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-700 dark:text-amber-400 shrink-0">
                            <Eye className="w-3 h-3 shrink-0" />
                            <span>Viewer &middot; {invite.targetProfileName}</span>
                          </span>
                        </div>
                        <p className="text-[var(--cf-fg-subtle)] flex items-center gap-1.5 flex-wrap">
                          <Key className="w-3 h-3 text-[var(--cf-fg-subtle)] shrink-0" />
                          <span>Code: <code className="font-mono bg-[var(--cf-surface-2)] px-1 py-0.5 rounded text-xs">{invite.inviteCode}</code></span>
                          <span>&middot;</span>
                          <span>
                            {invite.permissions.view_clinical ? 'Visit prep & clinical' : ''}
                            {invite.permissions.view_clinical && invite.permissions.view_paperwork ? ', ' : ''}
                            {invite.permissions.view_paperwork ? 'Insurance & paperwork' : ''}
                          </span>
                        </p>
                      </div>
                    </div>

                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/20 shrink-0"
                      onClick={() => handleRevokeInvite(invite.id)}
                      data-testid={`revoke-invite-${invite.id}`}
                    >
                      {t('family.revoke')}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Exported Share Bundles History */}
          <div className="space-y-3 pt-3 border-t border-[var(--cf-border)]">
            <span className="text-xs font-semibold uppercase tracking-wider text-[var(--cf-fg-subtle)] block">
              {t('family.recent_bundles')}
            </span>

            <div className="divide-y divide-[var(--cf-border)]" data-testid="bundles-list">
              {shareBundles.length === 0 ? (
                <p className="text-xs text-[var(--cf-fg-subtle)] italic py-2">{t('family.no_export_history')}</p>
              ) : (
                shareBundles.map((bundle) => (
                  <div key={bundle.id} className="py-2.5 flex items-center justify-between gap-3 text-xs">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="w-7 h-7 rounded-lg bg-[var(--cf-surface-2)] border border-[var(--cf-border)] flex items-center justify-center shrink-0 text-emerald-600 dark:text-emerald-400">
                        <Printer className="w-3.5 h-3.5 shrink-0" />
                      </div>
                      <div className="min-w-0">
                        <span className="font-medium text-[var(--cf-fg)] block truncate">{bundle.title}</span>
                        <span className="text-xs text-[var(--cf-fg-subtle)] block">
                          {bundle.profileName ? `${bundle.profileName} · ` : ''}Printed care sheet
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-[var(--cf-fg-subtle)] shrink-0">{bundle.exportedAt}</span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Local Privacy Reassurance Note */}
          <div className="p-3.5 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] flex items-start gap-3 text-xs text-[var(--cf-fg-muted)]">
            <Info className="w-4 h-4 text-emerald-600 dark:text-emerald-400 mt-0.5 shrink-0" />
            <p className="leading-relaxed">
              {t('family.local_privacy_note')}
            </p>
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
