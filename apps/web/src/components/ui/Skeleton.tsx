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

export type SkeletonVariant = 'text' | 'circular' | 'rectangular';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: SkeletonVariant;
  width?: string | number;
  height?: string | number;
  delay?: number;
  animate?: boolean;
}

const variantStyles: Record<SkeletonVariant, string> = {
  text: 'h-4 w-full rounded-[var(--cf-radius-sm)]',
  circular: 'rounded-full shrink-0',
  rectangular: 'rounded-[var(--cf-radius-md)]'
};

export const Skeleton = React.forwardRef<HTMLDivElement, SkeletonProps>(
  (
    {
      variant = 'rectangular',
      width,
      height,
      delay = 0,
      animate = true,
      className,
      style,
      ...props
    },
    ref
  ) => {
    const [visible, setVisible] = React.useState(delay === 0);

    React.useEffect(() => {
      if (delay <= 0) return;
      const timer = setTimeout(() => {
        setVisible(true);
      }, delay);
      return () => clearTimeout(timer);
    }, [delay]);

    if (!visible) {
      return null;
    }

    const inlineStyles: React.CSSProperties = {
      ...style,
      width: width !== undefined ? (typeof width === 'number' ? `${width}px` : width) : undefined,
      height: height !== undefined ? (typeof height === 'number' ? `${height}px` : height) : undefined
    };

    return (
      <div
        ref={ref}
        role="status"
        aria-busy="true"
        aria-hidden="true"
        style={inlineStyles}
        className={cn(
          'bg-[var(--cf-surface-2)]',
          animate ? 'animate-pulse' : '',
          variantStyles[variant],
          className
        )}
        {...props}
      />
    );
  }
);

Skeleton.displayName = 'Skeleton';
