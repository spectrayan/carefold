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

import * as React from 'react';
import { cn } from '@/lib/utils';

export type BadgeVariant = 'neutral' | 'success' | 'warning' | 'danger' | 'info';
export type BadgeSize = 'sm' | 'md';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  dot?: boolean;
  icon?: React.ReactNode;
}

const variantStyles: Record<BadgeVariant, string> = {
  neutral:
    'bg-[var(--cf-surface-2)] text-[var(--cf-fg-subtle)] border border-[var(--cf-border)]',
  success:
    'bg-[var(--cf-success-bg)] text-[var(--cf-success-fg)] border border-[var(--cf-success-border)]',
  warning:
    'bg-[var(--cf-warn-bg)] text-[var(--cf-warn-fg)] border border-[var(--cf-warn-border)]',
  danger:
    'bg-[var(--cf-danger-bg)] text-[var(--cf-danger-fg)] border border-[var(--cf-danger-border)]',
  info:
    'bg-[var(--cf-info-bg)] text-[var(--cf-info-fg)] border border-[var(--cf-info-border)]'
};

const dotColorStyles: Record<BadgeVariant, string> = {
  neutral: 'bg-[var(--cf-fg-subtle)]',
  success: 'bg-[var(--cf-success-fg)]',
  warning: 'bg-[var(--cf-warn-fg)]',
  danger: 'bg-[var(--cf-danger-fg)]',
  info: 'bg-[var(--cf-info-fg)]'
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'text-xs px-2 py-0.5 rounded-[var(--cf-radius-sm)]',
  md: 'text-xs sm:text-sm px-2.5 py-1 rounded-[var(--cf-radius-md)]'
};

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  (
    {
      variant = 'neutral',
      size = 'sm',
      dot = false,
      icon,
      children,
      className,
      ...props
    },
    ref
  ) => {
    return (
      <span
        ref={ref}
        role="status"
        className={cn(
          'inline-flex items-center font-medium gap-1.5 leading-none select-none tracking-tight',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        {...props}
      >
        {dot && (
          <span
            className={cn('w-1.5 h-1.5 rounded-full shrink-0', dotColorStyles[variant])}
            aria-hidden="true"
          />
        )}
        {icon && <span className="inline-flex shrink-0">{icon}</span>}
        <span>{children}</span>
      </span>
    );
  }
);

Badge.displayName = 'Badge';
