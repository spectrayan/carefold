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
