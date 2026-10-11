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
import { Eye, Shield, User, Sparkles, Lock, MessageSquare, FileText, Edit3, ArrowRight } from 'lucide-react';
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
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20 whitespace-nowrap">
          <User className="w-3.5 h-3.5 shrink-0" />
          <span>Self · you</span>
        </span>
      );
    }

    if (profile.role === 'guardian') {
      if (profile.age !== undefined && profile.age < 13) {
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)] whitespace-nowrap">
            <Shield className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
            <span>Child · no login</span>
          </span>
        );
      }
      if (profile.age !== undefined && profile.age >= 13 && profile.age < 18) {
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-500/10 text-purple-700 dark:text-purple-300 border border-purple-500/20 whitespace-nowrap">
            <Sparkles className="w-3.5 h-3.5 shrink-0" />
            <span>Teen login</span>
          </span>
        );
      }
      return (
        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-700/10 text-emerald-800 dark:text-emerald-300 border border-emerald-700/20 whitespace-nowrap">
          <Shield className="w-3.5 h-3.5 shrink-0" />
          <span>You manage</span>
        </span>
      );
    }

    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/20 whitespace-nowrap">
        <Eye className="w-3.5 h-3.5 shrink-0" />
        <span>Viewer</span>
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
        {/* Top Header: Avatar + Name & Relationship */}
        <div className="flex items-center gap-3">
          <Avatar name={profile.name} src={profile.avatarUrl} colorSlot={profile.colorSlot} size="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-[var(--cf-fg)] leading-snug truncate">
              {profile.name}
            </h2>
            <p className="text-xs text-[var(--cf-fg-subtle)] truncate">
              {profile.relationship} {profile.age ? `· ${profile.age} yrs` : ''}
            </p>
          </div>
        </div>

        {/* Role Badges Row */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {renderRoleBadge()}
        </div>

        {/* Stats Row */}
        <div className="flex items-center gap-3 text-xs text-[var(--cf-fg-muted)]">
          <span className="inline-flex items-center gap-1.5">
            <MessageSquare className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
            <span>{chatsCount} {chatsCount === 1 ? 'chat' : 'chats'}</span>
          </span>
          <span className="text-[var(--cf-border-strong)]">·</span>
          <span className="inline-flex items-center gap-1.5">
            <FileText className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
            <span>{itemsCount} {itemsCount === 1 ? 'item' : 'items'}</span>
          </span>
        </div>

        {/* Access Description */}
        <div className="text-xs text-[var(--cf-fg-muted)] flex items-center gap-1.5 pt-2.5 border-t border-[var(--cf-border)]">
          {profile.viewers && profile.viewers.length > 0 ? (
            <span className="inline-flex items-center gap-1.5 text-[var(--cf-fg-subtle)]">
              <Eye className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
              <span>{profile.viewers.join(', ')} can view visit prep</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-[var(--cf-fg-subtle)]">
              <Lock className="w-3.5 h-3.5 text-[var(--cf-fg-subtle)] shrink-0" />
              <span>Only you</span>
            </span>
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
            className="text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] inline-flex items-center gap-1.5 min-h-[36px] transition-colors"
          >
            <Edit3 className="w-3.5 h-3.5 shrink-0" />
            <span>Edit profile</span>
          </button>
        ) : (
          <span className="text-xs text-[var(--cf-fg-subtle)]">On this computer</span>
        )}
        <Link
          href={profilePath(profile.id)}
          className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 hover:underline inline-flex items-center gap-1 min-h-[36px]"
        >
          <span>Open dashboard</span>
          <ArrowRight className="w-3.5 h-3.5 shrink-0" />
        </Link>
      </div>
    </div>
  );
}
