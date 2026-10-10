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

import { redirect } from 'next/navigation';
import { cookies } from 'next/headers';

export const dynamic = 'force-dynamic';

export default async function RootPage() {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('carefold_session');

  // 1. Unauthenticated -> immediate redirect to /login
  if (!sessionCookie || !sessionCookie.value.trim()) {
    redirect('/login');
  }

  // 2. Validate session against backend before routing to dashboard
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  try {
    const res = await fetch(`${backendUrl}/api/v1/auth/me`, {
      headers: {
        cookie: `carefold_session=${sessionCookie.value}`,
        accept: 'application/json'
      },
      cache: 'no-store'
    });
    if (!res.ok) {
      redirect('/login');
    }
  } catch {
    redirect('/login');
  }

  // 3. Authenticated -> redirect to active profile (or /p/me)
  const activeProfileCookie = cookieStore.get('carefold_active_profile');
  const targetProfileId = activeProfileCookie?.value?.trim() || 'me';

  redirect(`/p/${targetProfileId}`);
}
