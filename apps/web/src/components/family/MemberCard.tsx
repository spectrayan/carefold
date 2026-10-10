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

import React, { useState } from 'react';
import Link from 'next/link';
import { Eye, Shield, User, Sparkles } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
import { cn } from '@/lib/utils';
import {
  type CareProfile,
  checkTeenHandoverStatus
} from '@/lib/familyProfiles';
import { profilePath } from '@/lib/routes';
import { TeenHandoverBanner } from './TeenHandoverBanner';

export interface MemberCardProps {
  profile: CareProfile;
  className?: string;
  onEdit?: (profile: CareProfile) => void;
}

export function MemberCard({ profile, className, onEdit }: MemberCardProps) {
  const [handoverDismissed, setHandoverDismissed] = useState(false);

  const handoverStatus = checkTeenHandoverStatus(profile);

  // Determine role badge copy & styling
  const renderRoleBadge = () => {
    if (profile.role === 'self') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
          <User className="w-3 h-3" />
          Self · you
        </span>
      );
    }

    if (profile.role === 'guardian') {
      if (profile.age !== undefined && profile.age < 13) {
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)]">
            <Shield className="w-3 h-3 text-[var(--cf-fg-subtle)]" />
            Child · no login
          </span>
        );
      }
      if (profile.age !== undefined && profile.age >= 13 && profile.age < 18) {
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-500/10 text-purple-700 dark:text-purple-300 border border-purple-500/20">
            <Sparkles className="w-3 h-3" />
            Teen login
          </span>
        );
      }
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500/10 text-blue-700 dark:text-blue-300 border border-blue-500/20">
          <Shield className="w-3 h-3" />
          You manage
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20">
        <Eye className="w-3 h-3" />
        Viewer
      </span>
    );
  };

  const chatsCount = profile.stats?.chats ?? 0;
  const itemsCount = profile.stats?.items ?? 0;

  return (
    <div
      data-testid={`member-card-${profile.id}`}
      className={cn(
        'p-5 rounded-2xl bg-[var(--cf-surface)] border border-[var(--cf-border)] shadow-sm flex flex-col justify-between gap-4 transition-all hover:border-[var(--cf-border-strong)]',
        className
      )}
    >
      <div className="space-y-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <Avatar name={profile.name} src={profile.avatarUrl} colorSlot={profile.colorSlot} size="lg" />
            <div>
              <h2 className="text-base font-semibold text-[var(--cf-fg)] leading-snug">
                {profile.name}
              </h2>
              <p className="text-xs text-[var(--cf-fg-subtle)]">
                {profile.relationship} {profile.age ? `· ${profile.age} yrs` : ''}
              </p>
            </div>
          </div>
          <div>{renderRoleBadge()}</div>
        </div>

        {/* Stats Row */}
        <div className="flex items-center gap-3 text-xs text-[var(--cf-fg-subtle)]">
          <span>{chatsCount} {chatsCount === 1 ? 'chat' : 'chats'}</span>
          <span>·</span>
          <span>{itemsCount} {itemsCount === 1 ? 'item' : 'items'}</span>
        </div>

        {/* Access Description */}
        <div className="text-xs text-[var(--cf-fg-muted)]">
          {profile.viewers && profile.viewers.length > 0 ? (
            <span className="flex items-center gap-1 text-[var(--cf-fg-subtle)]">
              <Eye className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)]" />
              {profile.viewers.join(', ')} can view visit prep
            </span>
          ) : (
            <span>Only you</span>
          )}
        </div>

        {/* Teen Transition Reminder */}
        {!handoverDismissed && handoverStatus.shouldShowReminder && (
          <TeenHandoverBanner
            profileId={profile.id}
            profileName={profile.name}
            status={handoverStatus}
            onDismissed={() => setHandoverDismissed(true)}
          />
        )}
      </div>

      <div className="pt-3 border-t border-[var(--cf-border)] flex items-center justify-between">
        {onEdit ? (
          <button
            type="button"
            onClick={() => onEdit(profile)}
            className="text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] inline-flex items-center gap-1 min-h-[36px]"
          >
            Edit profile
          </button>
        ) : (
          <span className="text-xs text-[var(--cf-fg-subtle)]">On this computer</span>
        )}
        <Link
          href={profilePath(profile.id)}
          className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline inline-flex items-center gap-1 min-h-[36px]"
        >
          Open dashboard &rarr;
        </Link>
      </div>
    </div>
  );
}
