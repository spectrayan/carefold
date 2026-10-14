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
import { Eye, Shield, User, ShieldCheck, Stethoscope, FileText } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
import { cn } from '@/lib/utils';
import { loadHouseholdProfiles, type CareProfile } from '@/lib/familyProfiles';

export interface RoleMatrixTableProps {
  profiles?: CareProfile[];
  className?: string;
}

export function RoleMatrixTable({ profiles: profilesProp, className }: RoleMatrixTableProps) {
  const [household, setHousehold] = React.useState<CareProfile[]>(() => profilesProp || []);

  React.useEffect(() => {
    if (profilesProp !== undefined) {
      setHousehold(profilesProp);
    } else {
      setHousehold(loadHouseholdProfiles());
    }
  }, [profilesProp]);

  // Derive members strictly from props or mounted state (avoids synchronous localStorage reads during SSR/hydration)
  const members: CareProfile[] = profilesProp !== undefined ? profilesProp : household;

  // Find self profile
  const selfMember = members.find((m: CareProfile) => m.role === 'self' || m.relationship.toLowerCase() === 'self') || members[0];
  const otherMembers = members.filter((m: CareProfile) => m.id !== selfMember?.id);

  // Read local viewer invitations to include pending/active invitees in matrix
  const [invitedViewers, setInvitedViewers] = React.useState<{ name: string; profileId?: string }[]>([]);

  React.useEffect(() => {
    try {
      const stored = localStorage.getItem('carefold_viewer_invitations');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) {
          setInvitedViewers(
            parsed
              .filter((inv: any) => inv && inv.inviteeName)
              .map((inv: any) => ({ name: String(inv.inviteeName), profileId: inv.targetProfileId ? String(inv.targetProfileId) : undefined }))
          );
        }
      }
    } catch {}
  }, []);

  // Extract all distinct viewers declared across profiles and invitations
  const allViewers: string[] = Array.from(
    new Set([
      ...members.flatMap((m: CareProfile) => m.viewers || []),
      ...invitedViewers.map((v) => v.name)
    ])
  ).filter(Boolean);

  return (
    <div
      data-testid="role-matrix-section"
      className={cn(
        'rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] p-5 shadow-sm space-y-4',
        className
      )}
    >
      <div>
        <h2 className="text-base font-bold text-[var(--cf-fg)] tracking-tight">
          Who can see what
        </h2>
        <p className="text-xs text-[var(--cf-fg-muted)] mt-1">
          Access governance matrix across profiles and viewers. Each person signing in only has access to their authorized dossiers.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table
          className="w-full text-sm border-collapse"
          aria-label="Access governance role matrix"
          data-testid="role-matrix-table"
        >
          <thead>
            <tr>
              <th
                scope="col"
                className="text-left py-2.5 px-3 text-xs uppercase tracking-wider text-[var(--cf-fg-subtle)] border-b border-[var(--cf-border)] whitespace-nowrap"
              >
                Person signing in
              </th>
              {members.map((member) => (
                <th
                  key={member.id}
                  scope="col"
                  className="text-left py-2.5 px-3 text-xs uppercase tracking-wider text-[var(--cf-fg-subtle)] border-b border-[var(--cf-border)] whitespace-nowrap"
                >
                  {member.role === 'self' || member.relationship.toLowerCase() === 'self'
                    ? `${member.name.split(' ')[0]} (You)`
                    : member.name.split(' ')[0]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {/* Account Owner / Self Row */}
            {selfMember && (
              <tr>
                <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal whitespace-nowrap">
                  <div className="flex items-center gap-2.5 font-semibold text-[var(--cf-fg)]">
                    <Avatar name={selfMember.name} size="xs" colorSlot={selfMember.colorSlot || 1} />
                    <div>
                      <span>{selfMember.name}</span>
                      <span className="block text-xs font-normal text-[var(--cf-fg-subtle)]">
                        Account owner
                      </span>
                    </div>
                  </div>
                </th>
                {members.map((col) => (
                  <td key={col.id} className="py-3 px-3 border-b border-[var(--cf-border)]">
                    {col.id === selfMember.id ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 whitespace-nowrap">
                        <User className="w-3.5 h-3.5 shrink-0" />
                        Self
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500/10 text-blue-700 dark:text-blue-300 whitespace-nowrap">
                        <Shield className="w-3.5 h-3.5 shrink-0" />
                        Guardian
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            )}

            {/* Managed Family Members with Login (e.g. Teens or Adult dependents) */}
            {otherMembers.map((member) => {
              const isTeen = Boolean(member.age && member.age >= 13 && member.age < 18);
              const hasLogin = isTeen || member.role === 'self';
              if (!hasLogin) return null; // Children without login do not have a sign-in row

              return (
                <tr key={member.id}>
                  <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal whitespace-nowrap">
                    <div className="flex items-center gap-2.5 font-semibold text-[var(--cf-fg)]">
                      <Avatar name={member.name} size="xs" colorSlot={member.colorSlot || 2} />
                      <div>
                        <span>{member.name}</span>
                        <span className="block text-xs font-normal text-[var(--cf-fg-subtle)]">
                          {isTeen ? 'Teen login' : 'Login account'}
                        </span>
                      </div>
                    </div>
                  </th>
                  {members.map((col) => (
                    <td key={col.id} className="py-3 px-3 border-b border-[var(--cf-border)] text-[var(--cf-fg-subtle)]">
                      {col.id === member.id ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 whitespace-nowrap">
                          <User className="w-3.5 h-3.5 shrink-0" />
                          Self
                        </span>
                      ) : (
                        <span>&mdash;</span>
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}

            {/* Viewers Rows */}
            {allViewers.map((viewerName) => (
              <tr key={viewerName}>
                <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal whitespace-nowrap">
                  <div className="flex items-center gap-2.5 font-semibold text-[var(--cf-fg)]">
                    <Avatar name={viewerName} size="xs" colorSlot={5} />
                    <div>
                      <span>{viewerName}</span>
                      <span className="block text-xs font-normal text-[var(--cf-fg-subtle)]">
                        Viewer
                      </span>
                    </div>
                  </div>
                </th>
                {members.map((col) => {
                  const hasAccess =
                    col.viewers?.includes(viewerName) ||
                    invitedViewers.some((inv) => inv.name === viewerName && inv.profileId === col.id);
                  return (
                    <td key={col.id} className="py-3 px-3 border-b border-[var(--cf-border)] text-[var(--cf-fg-subtle)]">
                      {hasAccess ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 whitespace-nowrap">
                          <Eye className="w-3.5 h-3.5 shrink-0" />
                          Viewer · visit prep
                        </span>
                      ) : (
                        <span>&mdash;</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Capabilities Description */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-3 text-xs text-[var(--cf-fg-muted)]">
        <div className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1.5">
          <div className="flex items-center gap-2 font-semibold text-[var(--cf-fg)]">
            <ShieldCheck className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>Guardian / Manage</span>
            <code className="text-xs text-[var(--cf-fg-subtle)] font-mono font-normal">(manage)</code>
          </div>
          <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
            Edit profile, invite viewers, configure care settings, and delete profiles.
          </p>
        </div>
        <div className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1.5">
          <div className="flex items-center gap-2 font-semibold text-[var(--cf-fg)]">
            <Stethoscope className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" />
            <span>Visit prep &amp; clinical</span>
            <code className="text-xs text-[var(--cf-fg-subtle)] font-mono font-normal">(view_clinical)</code>
          </div>
          <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
            Read clinical notes, visit prep dossiers, and consult clinical assist agents.
          </p>
        </div>
        <div className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1.5">
          <div className="flex items-center gap-2 font-semibold text-[var(--cf-fg)]">
            <FileText className="w-4 h-4 text-purple-600 dark:text-purple-400 shrink-0" />
            <span>Insurance &amp; paperwork</span>
            <code className="text-xs text-[var(--cf-fg-subtle)] font-mono font-normal">(view_paperwork)</code>
          </div>
          <p className="text-xs text-[var(--cf-fg-muted)] leading-relaxed">
            Read insurance policies, claims, appeals, formulary, and prior authorizations.
          </p>
        </div>
      </div>
    </div>
  );
}
