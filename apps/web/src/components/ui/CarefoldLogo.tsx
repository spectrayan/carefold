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

import React from 'react';
import { cn } from '@/lib/utils';

export interface CarefoldLogoProps {
  /** Pixel dimension of the square folded-care mark (default: 28) */
  size?: number;
  /** Whether to render the adjacent "Carefold" wordmark text */
  showWordmark?: boolean;
  /** Additional CSS classes applied to the wrapper or SVG */
  className?: string;
}

export function CarefoldLogo({
  size = 28,
  showWordmark = false,
  className = ''
}: CarefoldLogoProps) {
  const uid = React.useId().replace(/:/g, '');
  const bgGradientId = `cf-emerald-bg-${uid}`;
  const foldGradientId = `cf-fold-mid-${uid}`;

  return (
    <span
      data-testid="carefold-logo"
      className={cn('inline-flex items-center gap-2 shrink-0 select-none', className)}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="Carefold brand mark"
        className="shrink-0"
      >
        <defs>
          <linearGradient
            id={bgGradientId}
            x1="6"
            y1="6"
            x2="58"
            y2="58"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#047857" />
          </linearGradient>
          <linearGradient
            id={foldGradientId}
            x1="20"
            y1="28"
            x2="48"
            y2="50"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#6EE7B7" />
            <stop offset="100%" stopColor="#10B981" />
          </linearGradient>
        </defs>
        <rect
          x="4"
          y="4"
          width="56"
          height="56"
          rx="16"
          fill={`url(#${bgGradientId})`}
        />
        <path
          d="M32 13L48 22.5L32 32L16 22.5L32 13Z"
          fill="#FAF9F5"
        />
        <path
          d="M16 22.5L32 32V51L16 40.5V22.5Z"
          fill="#FAF9F5"
          fillOpacity="0.88"
        />
        <path
          d="M48 22.5L32 32V51L48 40.5V22.5Z"
          fill={`url(#${foldGradientId})`}
        />
        <path
          d="M32 18V45M23 27.5L32 32L41 27.5"
          stroke="#047857"
          strokeWidth="2.25"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {showWordmark && (
        <span
          data-testid="carefold-logo-wordmark"
          className="font-bold tracking-tight text-[var(--cf-fg)]"
        >
          Carefold
        </span>
      )}
    </span>
  );
}

export default CarefoldLogo;
