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

export type ChipVariant = 'neutral' | 'selected' | 'solid' | 'local' | 'warning' | 'info';
export type ChipSize = 'sm' | 'md' | 'lg';

export interface ChipProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ChipVariant;
  size?: ChipSize;
  selected?: boolean;
  removable?: boolean;
  onRemove?: (e: React.MouseEvent) => void;
  icon?: React.ReactNode;
}

const variantStyles: Record<ChipVariant, string> = {
  neutral:
    'bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)] hover:bg-[var(--cf-surface-3)] hover:text-[var(--cf-fg)]',
  selected:
    'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)] border border-[var(--cf-success-border)] font-medium',
  solid:
    'bg-[var(--cf-fg)] text-[var(--cf-canvas)] border border-[var(--cf-fg)]',
  local:
    'bg-[var(--cf-local-bg)] text-[var(--cf-local-fg)] border border-[var(--cf-success-border)]',
  warning:
    'bg-[var(--cf-warn-bg)] text-[var(--cf-warn-fg)] border border-[var(--cf-warn-border)]',
  info:
    'bg-[var(--cf-info-bg)] text-[var(--cf-info-fg)] border border-[var(--cf-info-border)]'
};

const sizeStyles: Record<ChipSize, string> = {
  sm: 'h-6 text-xs px-2.5 rounded-[var(--cf-radius-full)]',
  md: 'h-8 text-xs sm:text-sm px-3 rounded-[var(--cf-radius-full)]',
  lg: 'h-9 text-sm px-3.5 rounded-[var(--cf-radius-full)]'
};

export const Chip = React.forwardRef<HTMLButtonElement, ChipProps>(
  (
    {
      variant = 'neutral',
      size = 'md',
      selected = false,
      removable = false,
      onRemove,
      icon,
      children,
      className,
      disabled = false,
      onClick,
      onKeyDown,
      type = 'button',
      ...props
    },
    ref
  ) => {
    const effectiveVariant = selected ? 'selected' : variant;

    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (removable && (e.key === 'Backspace' || e.key === 'Delete')) {
        e.preventDefault();
        e.stopPropagation();
        onRemove?.(e as unknown as React.MouseEvent);
      }
      onKeyDown?.(e);
    };

    const handleRemoveClick = (e: React.MouseEvent) => {
      e.stopPropagation();
      onRemove?.(e);
    };

    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled}
        aria-pressed={selected !== undefined ? selected : undefined}
        onClick={onClick}
        onKeyDown={handleKeyDown}
        className={cn(
          'relative inline-flex items-center justify-center font-medium gap-1.5 transition-colors select-none',
          'focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] focus-visible:outline-offset-2',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          // 44px min tap area via transparent hit pseudo-element
          'before:absolute before:-inset-y-2 before:inset-x-0 before:content-[\'\']',
          variantStyles[effectiveVariant],
          sizeStyles[size],
          className
        )}
        {...props}
      >
        {icon && <span className="inline-flex shrink-0">{icon}</span>}
        <span className="truncate">{children}</span>
        {removable && (
          <span
            role="button"
            tabIndex={-1}
            aria-label="Delete"
            onClick={handleRemoveClick}
            className="ml-0.5 inline-flex items-center justify-center rounded-full hover:bg-[rgba(0,0,0,0.1)] dark:hover:bg-[rgba(255,255,255,0.15)] p-0.5 cursor-pointer text-current"
          >
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </span>
        )}
      </button>
    );
  }
);

Chip.displayName = 'Chip';
