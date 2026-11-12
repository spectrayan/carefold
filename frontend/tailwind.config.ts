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

import type { Config } from 'tailwindcss';
import { yarvellePreset } from '@yarvelle/ui/tailwind-preset';
import { yarvelleUiContentGlob } from '@yarvelle/ui/tokens';

const config: Config = {
  presets: [yarvellePreset],
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/health-ui/**/*.{js,ts,jsx,tsx,mdx}',
    './src/lib/**/*.{js,ts,jsx,tsx}',
    yarvelleUiContentGlob()
  ],
  theme: {
    extend: {
      colors: {
        // Carefold legacy border/status line & brand aliases extending yarvellePreset
        line: {
          DEFAULT: 'var(--cf-border)',
          strong: 'var(--cf-border-strong)'
        },
        brand: {
          DEFAULT: 'var(--cf-brand)',
          mint: 'var(--cf-brand-mint)'
        },
        info: {
          line: 'var(--cf-info-border)'
        },
        warn: {
          line: 'var(--cf-warn-border)'
        },
        danger: {
          line: 'var(--cf-danger-border)'
        },
        success: {
          line: 'var(--cf-success-border)'
        },

        // Legacy / shadcn bridge aliases
        background: 'var(--cf-canvas)',
        foreground: 'var(--cf-fg)',
        card: {
          DEFAULT: 'var(--cf-surface)',
          foreground: 'var(--cf-fg)'
        },
        popover: {
          DEFAULT: 'var(--cf-surface)',
          foreground: 'var(--cf-fg)'
        },
        muted: {
          DEFAULT: 'var(--cf-surface-2)',
          foreground: 'var(--cf-fg-muted)'
        },
        input: 'var(--cf-border-strong)',
        ring: 'var(--cf-focus)',

        // Carefold domain risk-tier tokens (coexist with yarvellePreset risk.low..critical)
        risk: {
          wellness: {
            bg: '#f0fdf4',
            text: '#166534',
            border: '#bbf7d0'
          },
          admin: {
            bg: '#eff6ff',
            text: '#1e40af',
            border: '#bfdbfe'
          },
          education: {
            bg: '#faf5ff',
            text: '#6b21a8',
            border: '#e9d5ff'
          },
          assist: {
            bg: '#fffbeb',
            text: '#b45309',
            border: '#fde68a'
          },
          clinical_assist: {
            bg: '#fffbeb',
            text: '#b45309',
            border: '#fde68a'
          }
        }
      },
      fontFamily: {
        sans: [
          'var(--font-inter)',
          'var(--ui-font-sans)',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif'
        ],
        display: [
          'var(--font-fraunces)',
          'var(--ui-font-display)',
          '"Iowan Old Style"',
          'Georgia',
          'serif'
        ],
        mono: [
          'var(--ui-font-mono, ui-monospace)',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace'
        ]
      },
      transitionTimingFunction: { cf: 'var(--cf-ease)' },
      keyframes: {
        pulseDot: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.3' }
        }
      },
      animation: {
        'pulse-dot': 'pulseDot 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite'
      }
    }
  },
  plugins: []
};

export default config;
