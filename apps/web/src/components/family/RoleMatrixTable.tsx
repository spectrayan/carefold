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

import React from 'react';
import { Eye, Shield, User } from 'lucide-react';
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

  // Extract all distinct viewers declared across profiles
  const allViewers: string[] = Array.from(
    new Set(members.flatMap((m: CareProfile) => m.viewers || []))
  );

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
                className="text-left py-2.5 px-3 text-xs uppercase tracking-wider text-[var(--cf-fg-subtle)] border-b border-[var(--cf-border)]"
              >
                Person signing in
              </th>
              {members.map((member) => (
                <th
                  key={member.id}
                  scope="col"
                  className="text-left py-2.5 px-3 text-xs uppercase tracking-wider text-[var(--cf-fg-subtle)] border-b border-[var(--cf-border)]"
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
                <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal">
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
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                        <User className="w-3 h-3" />
                        Self
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-500/10 text-blue-700 dark:text-blue-300">
                        <Shield className="w-3 h-3" />
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
                  <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal">
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
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400">
                          <User className="w-3 h-3" />
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
                <th scope="row" className="py-3 px-3 border-b border-[var(--cf-border)] text-left font-normal">
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
                  const hasAccess = col.viewers?.includes(viewerName);
                  return (
                    <td key={col.id} className="py-3 px-3 border-b border-[var(--cf-border)] text-[var(--cf-fg-subtle)]">
                      {hasAccess ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300">
                          <Eye className="w-3 h-3" />
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
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 text-xs text-[var(--cf-fg-muted)]">
        <div className="p-2.5 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1">
          <span className="font-semibold text-[var(--cf-fg)] block">manage</span>
          <span>Edit profile, invite viewers, configure care settings and delete profiles.</span>
        </div>
        <div className="p-2.5 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1">
          <span className="font-semibold text-[var(--cf-fg)] block">view_clinical</span>
          <span>Read clinical notes, visit prep dossiers, and consult clinical assist agents.</span>
        </div>
        <div className="p-2.5 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1">
          <span className="font-semibold text-[var(--cf-fg)] block">view_paperwork</span>
          <span>Read insurance policies, claims, appeals, formulary, and prior authorizations.</span>
        </div>
      </div>
    </div>
  );
}
