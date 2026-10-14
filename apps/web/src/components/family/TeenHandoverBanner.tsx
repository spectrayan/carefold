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

import { AlertCircle, UserCheck } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import {
  type TeenHandoverStatus,
  dismissTeenHandoverReminder
} from '@/lib/familyProfiles';

export interface TeenHandoverBannerProps {
  profileId: string;
  profileName: string;
  status: TeenHandoverStatus;
  onDismissed?: () => void;
  className?: string;
}

export function TeenHandoverBanner({
  profileId,
  profileName,
  status,
  onDismissed,
  className
}: TeenHandoverBannerProps) {
  if (!status.shouldShowReminder) return null;

  const firstName = profileName.split(' ')[0];

  const handleDismiss = () => {
    dismissTeenHandoverReminder(profileId);
    onDismissed?.();
  };

  return (
    <div
      role="region"
      aria-label={`Teen transition notice for ${profileName}`}
      data-testid={`teen-handover-banner-${profileId}`}
      className={cn(
        'p-3.5 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-200 text-xs space-y-2.5',
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-amber-950 dark:text-amber-100">
            {status.hasReached18
              ? `${firstName} has reached age 18`
              : `${firstName} turns 18 in ${status.daysRemaining} days (${status.turning18Date})`}
          </p>
          <p className="text-amber-800 dark:text-amber-300 leading-relaxed">
            {status.hasReached18
              ? `${firstName} is eligible for independent account ownership. You can transition records to their own Carefold account.`
              : `Plan handover to an independent Carefold account so ${firstName} can manage their own medical visit prep and paperwork.`}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="primary"
          size="sm"
          className="text-xs h-7 px-2.5"
          onClick={() => {
            alert(`Invitation link generated for ${firstName} to claim their independent account.`);
            handleDismiss();
          }}
        >
          <UserCheck className="w-3.5 h-3.5 mr-1" />
          Invite to own account
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-xs h-7 px-2.5 text-amber-800 dark:text-amber-300 hover:bg-amber-500/20"
          onClick={handleDismiss}
        >
          Remind me in 30 days
        </Button>
      </div>
    </div>
  );
}
