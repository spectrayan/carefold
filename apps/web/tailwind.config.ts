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

import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}'
  ],
  theme: {
    extend: {
      colors: {
        // Direct semantic tokens
        canvas: 'var(--cf-canvas)',
        surface: {
          DEFAULT: 'var(--cf-surface)',
          2: 'var(--cf-surface-2)',
          3: 'var(--cf-surface-3)'
        },
        rail: 'var(--cf-rail)',
        fg: {
          DEFAULT: 'var(--cf-fg)',
          muted: 'var(--cf-fg-muted)',
          subtle: 'var(--cf-fg-subtle)',
          'on-primary': 'var(--cf-fg-on-primary)',
          link: 'var(--cf-fg-link)'
        },
        line: {
          DEFAULT: 'var(--cf-border)',
          strong: 'var(--cf-border-strong)'
        },
        primary: {
          DEFAULT: 'var(--cf-primary)',
          hover: 'var(--cf-primary-hover)',
          soft: 'var(--cf-primary-soft)',
          'soft-fg': 'var(--cf-primary-soft-fg)'
        },
        brand: {
          DEFAULT: 'var(--cf-brand)',
          mint: 'var(--cf-brand-mint)'
        },
        info: {
          bg: 'var(--cf-info-bg)',
          fg: 'var(--cf-info-fg)',
          line: 'var(--cf-info-border)'
        },
        warn: {
          bg: 'var(--cf-warn-bg)',
          fg: 'var(--cf-warn-fg)',
          line: 'var(--cf-warn-border)'
        },
        danger: {
          bg: 'var(--cf-danger-bg)',
          fg: 'var(--cf-danger-fg)',
          line: 'var(--cf-danger-border)'
        },
        success: {
          bg: 'var(--cf-success-bg)',
          fg: 'var(--cf-success-fg)',
          line: 'var(--cf-success-border)'
        },
        emergency: {
          DEFAULT: 'var(--cf-emergency)',
          fg: 'var(--cf-emergency-fg)'
        },
        focus: 'var(--cf-focus)',
        member: {
          1: { bg: 'var(--cf-member-1-bg)', fg: 'var(--cf-member-1-fg)' },
          2: { bg: 'var(--cf-member-2-bg)', fg: 'var(--cf-member-2-fg)' },
          3: { bg: 'var(--cf-member-3-bg)', fg: 'var(--cf-member-3-fg)' },
          4: { bg: 'var(--cf-member-4-bg)', fg: 'var(--cf-member-4-fg)' },
          5: { bg: 'var(--cf-member-5-bg)', fg: 'var(--cf-member-5-fg)' }
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
        border: 'var(--cf-border)',
        input: 'var(--cf-border-strong)',
        ring: 'var(--cf-focus)',

        // Backward-compatible risk tokens
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
          'var(--cf-font-sans)',
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
          'var(--cf-font-display)',
          '"Iowan Old Style"',
          'Georgia',
          'serif'
        ],
        mono: [
          'var(--cf-font-mono, ui-monospace)',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace'
        ]
      },
      fontSize: {
        xs: ['var(--cf-text-xs)', { lineHeight: 'var(--cf-leading-xs)' }],
        sm: ['var(--cf-text-sm)', { lineHeight: 'var(--cf-leading-sm)' }],
        base: ['var(--cf-text-md)', { lineHeight: 'var(--cf-leading-md)' }],
        lg: ['var(--cf-text-lg)', { lineHeight: 'var(--cf-leading-lg)' }],
        xl: ['var(--cf-text-xl)', { lineHeight: 'var(--cf-leading-xl)' }],
        '2xl': ['var(--cf-text-2xl)', { lineHeight: 'var(--cf-leading-2xl)' }],
        '3xl': ['var(--cf-text-3xl)', { lineHeight: 'var(--cf-leading-3xl)' }],
        '4xl': ['var(--cf-text-4xl)', { lineHeight: 'var(--cf-leading-4xl)' }]
      },
      borderRadius: {
        sm: 'var(--cf-radius-sm)',
        md: 'var(--cf-radius-md)',
        lg: 'var(--cf-radius-lg)',
        xl: 'var(--cf-radius-xl)',
        full: 'var(--cf-radius-full)'
      },
      boxShadow: {
        1: 'var(--cf-shadow-1)',
        2: 'var(--cf-shadow-2)',
        3: 'var(--cf-shadow-3)'
      },
      minHeight: { tap: 'var(--cf-tap)' },
      minWidth: { tap: 'var(--cf-tap)' },
      transitionTimingFunction: { cf: 'var(--cf-ease)' },
      transitionDuration: { fast: '120ms', base: '200ms', slow: '320ms' },
      zIndex: {
        rail: '20',
        sticky: '30',
        popover: '40',
        modal: '50',
        toast: '60',
        skip: '70'
      },
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
