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
import { Button } from './Button';

export interface InlineErrorProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  message: string;
  technicalDetails?: string;
  onRetry?: () => void;
  retryLabel?: string;
  action?: React.ReactNode;
  severity?: 'error' | 'warning';
}

export const InlineError = React.forwardRef<HTMLDivElement, InlineErrorProps>(
  (
    {
      title,
      message,
      technicalDetails,
      onRetry,
      retryLabel = 'Try again',
      action,
      severity = 'error',
      className,
      ...props
    },
    ref
  ) => {
    const isWarning = severity === 'warning';

    return (
      <div
        ref={ref}
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className={cn(
          'rounded-[var(--cf-radius-lg)] p-4 text-left transition-all',
          isWarning
            ? 'bg-[var(--cf-warn-bg)] border border-[var(--cf-warn-border)] text-[var(--cf-warn-fg)]'
            : 'bg-[var(--cf-danger-bg)] border border-[var(--cf-danger-border)] text-[var(--cf-danger-fg)]',
          className
        )}
        {...props}
      >
        <div className="flex items-start gap-3">
          {/* Status Icon */}
          <div className="shrink-0 mt-0.5">
            {isWarning ? (
              <svg
                className="w-5 h-5 text-current"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                />
              </svg>
            ) : (
              <svg
                className="w-5 h-5 text-current"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            )}
          </div>

          {/* Content Column */}
          <div className="flex-1 min-w-0">
            {title && (
              <h4 className="font-semibold text-sm mb-1 text-[var(--cf-fg)] tracking-tight">
                {title}
              </h4>
            )}
            <p className="text-sm text-[var(--cf-fg)] leading-relaxed">
              {message}
            </p>

            {(onRetry || action) && (
              <div className="mt-3 flex items-center gap-2">
                {onRetry && (
                  <Button
                    variant={isWarning ? 'secondary' : 'danger'}
                    size="sm"
                    onClick={onRetry}
                  >
                    {retryLabel}
                  </Button>
                )}
                {action}
              </div>
            )}

            {technicalDetails && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer font-medium text-[var(--cf-fg-subtle)] hover:text-[var(--cf-fg)] select-none">
                  Show technical details
                </summary>
                <pre className="mt-2 p-2.5 rounded-[var(--cf-radius-sm)] bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] border border-[var(--cf-border)] overflow-x-auto max-h-60 font-mono text-xs whitespace-pre-wrap break-all">
                  {technicalDetails}
                </pre>
              </details>
            )}
          </div>
        </div>
      </div>
    );
  }
);

InlineError.displayName = 'InlineError';
