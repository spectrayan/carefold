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

import * as React from 'react';
import { cn } from '@/lib/utils';
import { Button, ButtonVariant } from './Button';

export interface EmptyStateAction {
  label: string;
  onClick: () => void;
  icon?: React.ReactNode;
  variant?: ButtonVariant;
}

export interface EmptyStateProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: EmptyStateAction;
  secondaryAction?: EmptyStateAction;
}

export const EmptyState = React.forwardRef<HTMLDivElement, EmptyStateProps>(
  (
    {
      icon,
      title,
      description,
      action,
      secondaryAction,
      className,
      ...props
    },
    ref
  ) => {
    return (
      <div
        ref={ref}
        className={cn(
          'flex flex-col items-center justify-center text-center p-8 sm:p-12',
          'rounded-[var(--cf-radius-xl)] bg-[var(--cf-surface)] border border-[var(--cf-border)]',
          className
        )}
        {...props}
      >
        <div
          className="w-12 h-12 rounded-full bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] flex items-center justify-center mb-4 shrink-0 shadow-1"
          aria-hidden="true"
        >
          {icon}
        </div>

        <h3 className="font-semibold text-lg text-[var(--cf-fg)] mb-2 tracking-tight">
          {title}
        </h3>

        <p className="text-sm text-[var(--cf-fg-muted)] max-w-sm mb-6 leading-relaxed">
          {description}
        </p>

        {(action || secondaryAction) && (
          <div className="flex flex-wrap items-center justify-center gap-3">
            {action && (
              <Button
                variant={action.variant || 'primary'}
                onClick={action.onClick}
                leftIcon={action.icon}
              >
                {action.label}
              </Button>
            )}
            {secondaryAction && (
              <Button
                variant={secondaryAction.variant || 'secondary'}
                onClick={secondaryAction.onClick}
                leftIcon={secondaryAction.icon}
              >
                {secondaryAction.label}
              </Button>
            )}
          </div>
        )}
      </div>
    );
  }
);

EmptyState.displayName = 'EmptyState';
