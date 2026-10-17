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

import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: process.env.BUILD_STANDALONE === 'true' ? 'standalone' : undefined,
  reactStrictMode: true,
  typescript: {
    ignoreBuildErrors: false
  },
  async redirects() {
    return [
      {
        source: '/skills',
        destination: '/helpers?tab=skills',
        permanent: false
      },
      {
        source: '/skills/:id',
        destination: '/helpers/skills/:id',
        permanent: false
      },
      {
        source: '/agents/:id',
        destination: '/helpers/:id',
        permanent: false
      },
      {
        source: '/settings',
        destination: '/settings/model',
        permanent: false
      },
      {
        source: '/library',
        destination: '/p/me/library',
        permanent: false
      },
      {
        source: '/chat',
        destination: '/p/me/chat',
        permanent: false
      }
    ];
  },
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: '/api/:path*',
      },
    ];
  }
};

export default nextConfig;
