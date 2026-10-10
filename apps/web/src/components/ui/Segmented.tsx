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

export interface SegmentedOption {
  value: string;
  label: string;
  badge?: string | number;
  disabled?: boolean;
  icon?: React.ReactNode;
}

export interface SegmentedProps {
  options: SegmentedOption[];
  value: string;
  onChange: (value: string) => void;
  size?: 'sm' | 'md';
  name?: string;
  'aria-label': string;
  className?: string;
}

export const Segmented = React.forwardRef<HTMLDivElement, SegmentedProps>(
  (
    {
      options,
      value,
      onChange,
      size = 'md',
      name,
      'aria-label': ariaLabel,
      className
    },
    ref
  ) => {
    const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
      const enabledOptions = options.filter((o) => !o.disabled);
      if (enabledOptions.length === 0) return;

      const currentIndex = enabledOptions.findIndex((o) => o.value === value);
      let targetIndex = currentIndex;

      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault();
        targetIndex = (currentIndex + 1) % enabledOptions.length;
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault();
        targetIndex = (currentIndex - 1 + enabledOptions.length) % enabledOptions.length;
      } else if (e.key === 'Home') {
        e.preventDefault();
        targetIndex = 0;
      } else if (e.key === 'End') {
        e.preventDefault();
        targetIndex = enabledOptions.length - 1;
      } else {
        return;
      }

      const targetOption = enabledOptions[targetIndex];
      if (targetOption) {
        onChange(targetOption.value);
        const el = document.getElementById(`seg-${targetOption.value}`);
        el?.focus();
      }
    };

    return (
      <div
        ref={ref}
        role="radiogroup"
        aria-label={ariaLabel}
        onKeyDown={handleKeyDown}
        className={cn(
          'inline-flex items-center rounded-[var(--cf-radius-lg)] p-1 bg-[var(--cf-surface-2)] border border-[var(--cf-border)]',
          className
        )}
      >
        {options.map((option) => {
          const isSelected = value === option.value;
          const isDisabled = !!option.disabled;

          return (
            <button
              key={option.value}
              id={`seg-${option.value}`}
              type="button"
              role="radio"
              name={name}
              disabled={isDisabled}
              aria-checked={isSelected}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => {
                if (!isDisabled) onChange(option.value);
              }}
              className={cn(
                'relative inline-flex items-center justify-center font-medium transition-all select-none gap-1.5',
                'min-h-[44px] px-3.5 py-1.5 rounded-[var(--cf-radius-md)]',
                'focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] focus-visible:outline-offset-2',
                'disabled:opacity-40 disabled:cursor-not-allowed',
                size === 'sm' ? 'text-xs' : 'text-sm',
                isSelected
                  ? 'bg-[var(--cf-surface)] text-[var(--cf-fg)] shadow-1 font-semibold'
                  : 'text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-3)]'
              )}
            >
              {option.icon && <span className="inline-flex shrink-0">{option.icon}</span>}
              <span>{option.label}</span>
              {option.badge !== undefined && (
                <span
                  className={cn(
                    'px-1.5 py-0.2 text-xs rounded-full font-semibold',
                    isSelected
                      ? 'bg-[var(--cf-primary-soft)] text-[var(--cf-primary-soft-fg)]'
                      : 'bg-[var(--cf-surface-3)] text-[var(--cf-fg-subtle)]'
                  )}
                >
                  {option.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  }
);

Segmented.displayName = 'Segmented';
