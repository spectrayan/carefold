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

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--cf-primary)] hover:bg-[var(--cf-primary-hover)] active:bg-[var(--cf-primary-hover)] text-[var(--cf-fg-on-primary)] border border-transparent shadow-1',
  secondary:
    'bg-[var(--cf-surface)] hover:bg-[var(--cf-surface-2)] active:bg-[var(--cf-surface-3)] text-[var(--cf-fg)] border border-[var(--cf-border-strong)] shadow-1',
  ghost:
    'bg-transparent hover:bg-[var(--cf-surface-2)] active:bg-[var(--cf-surface-3)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] border border-transparent',
  outline:
    'bg-transparent hover:bg-[var(--cf-surface-2)] active:bg-[var(--cf-surface-3)] text-[var(--cf-fg)] border border-[var(--cf-border-strong)]',
  danger:
    'bg-[var(--cf-danger-bg)] hover:bg-[var(--cf-danger-fg)] text-[var(--cf-danger-fg)] hover:text-white border border-[var(--cf-danger-border)]'
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-[34px] px-3 text-sm rounded-[var(--cf-radius-md)] relative before:absolute before:-inset-y-1.5 before:inset-x-0 before:content-[\'\']',
  md: 'min-h-[44px] h-10 px-4 text-sm rounded-[var(--cf-radius-md)]',
  lg: 'min-h-[48px] h-12 px-5 text-base rounded-[var(--cf-radius-md)]'
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      disabled = false,
      leftIcon,
      rightIcon,
      children,
      className,
      type = 'button',
      onClick,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading;

    const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
      if (isDisabled) {
        e.preventDefault();
        return;
      }
      onClick?.(e);
    };

    return (
      <button
        ref={ref}
        type={type}
        disabled={isDisabled}
        aria-busy={loading ? 'true' : undefined}
        onClick={handleClick}
        className={cn(
          'inline-flex items-center justify-center font-medium transition-colors select-none',
          'focus-visible:outline-2 focus-visible:outline-[var(--cf-focus)] focus-visible:outline-offset-2',
          'disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        {...props}
      >
        {loading && (
          <svg
            className="animate-spin -ml-1 mr-2 h-4 w-4 text-current"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        )}
        {!loading && leftIcon && <span className="mr-2 inline-flex shrink-0">{leftIcon}</span>}
        <span>{children}</span>
        {rightIcon && <span className="ml-2 inline-flex shrink-0">{rightIcon}</span>}
      </button>
    );
  }
);

Button.displayName = 'Button';
