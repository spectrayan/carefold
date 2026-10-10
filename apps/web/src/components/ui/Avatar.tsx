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

export type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';
export type MemberColorSlot = 1 | 2 | 3 | 4 | 5 | 'auto';

export interface AvatarProps extends React.HTMLAttributes<HTMLSpanElement> {
  name: string;
  colorSlot?: MemberColorSlot;
  size?: AvatarSize;
  src?: string;
  alt?: string;
  fallbackIcon?: React.ReactNode;
}

export function getInitials(name: string): string {
  if (!name || typeof name !== 'string') return '?';
  const trimmed = name.trim();
  if (!trimmed) return '?';

  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function hashNameToSlot(name: string): 1 | 2 | 3 | 4 | 5 {
  if (!name) return 1;
  let hash = 5381;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 33) ^ name.charCodeAt(i);
  }
  const slot = (Math.abs(hash) % 5) + 1;
  return slot as 1 | 2 | 3 | 4 | 5;
}

const slotStyles: Record<1 | 2 | 3 | 4 | 5, string> = {
  1: 'bg-[var(--cf-member-1-bg)] text-[var(--cf-member-1-fg)]',
  2: 'bg-[var(--cf-member-2-bg)] text-[var(--cf-member-2-fg)]',
  3: 'bg-[var(--cf-member-3-bg)] text-[var(--cf-member-3-fg)]',
  4: 'bg-[var(--cf-member-4-bg)] text-[var(--cf-member-4-fg)]',
  5: 'bg-[var(--cf-member-5-bg)] text-[var(--cf-member-5-fg)]'
};

const sizeStyles: Record<AvatarSize, { container: string; text: string }> = {
  xs: { container: 'w-[22px] h-[22px]', text: 'text-[10px]' },
  sm: { container: 'w-[26px] h-[26px]', text: 'text-[11px]' },
  md: { container: 'w-[34px] h-[34px]', text: 'text-sm font-semibold' },
  lg: { container: 'w-[56px] h-[56px]', text: 'text-xl font-bold' },
  xl: { container: 'w-[64px] h-[64px]', text: 'text-2xl font-bold' }
};

export const Avatar = React.forwardRef<HTMLSpanElement, AvatarProps>(
  (
    {
      name,
      colorSlot = 'auto',
      size = 'md',
      src,
      alt,
      fallbackIcon,
      className,
      ...props
    },
    ref
  ) => {
    const [imageError, setImageError] = React.useState(false);
    const effectiveSlot = colorSlot === 'auto' || !colorSlot ? hashNameToSlot(name) : colorSlot;
    const initials = getInitials(name);
    const isShowingImage = Boolean(src && !imageError);
    const resolvedSize = sizeStyles[size];

    return (
      <span
        ref={ref}
        role={isShowingImage ? undefined : 'img'}
        aria-label={isShowingImage ? undefined : (alt || name || 'Avatar')}
        className={cn(
          'relative inline-flex items-center justify-center rounded-full overflow-hidden shrink-0 select-none font-medium',
          slotStyles[effectiveSlot],
          resolvedSize.container,
          resolvedSize.text,
          className
        )}
        {...props}
      >
        {src && !imageError ? (
          <img
            src={src}
            alt={alt || name}
            onError={() => setImageError(true)}
            className="w-full h-full object-cover"
          />
        ) : fallbackIcon && !name ? (
          <span className="inline-flex items-center justify-center text-current">
            {fallbackIcon}
          </span>
        ) : (
          <span>{initials}</span>
        )}
      </span>
    );
  }
);

Avatar.displayName = 'Avatar';
