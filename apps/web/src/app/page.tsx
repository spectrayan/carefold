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
      const errorParam = res.status === 503 ? 'service_unavailable' : 'session_expired';
      redirect(`/login?error=${errorParam}`);
    }
  } catch {
    redirect('/login?error=service_unavailable');
  }

  // 3. Authenticated -> redirect to active profile (or /p/me)
  const activeProfileCookie = cookieStore.get('carefold_active_profile');
  const targetProfileId = activeProfileCookie?.value?.trim() || 'me';

  redirect(`/p/${targetProfileId}`);
}
