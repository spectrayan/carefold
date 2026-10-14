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

import React from 'react';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

interface ProfileLayoutProps {
  children: React.ReactNode;
  params: Promise<{ profileId: string }>;
}

export default async function ProfileLayout({ children, params }: ProfileLayoutProps) {
  const { profileId } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('carefold_session');

  // 1. Unauthenticated -> redirect to /login
  if (!sessionCookie || !sessionCookie.value.trim()) {
    redirect(`/login?redirect=${encodeURIComponent(`/p/${profileId}`)}`);
  }

  // 2. Validate session against backend service
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
      redirect(`/login?error=${errorParam}&redirect=${encodeURIComponent(`/p/${profileId}`)}`);
    }
  } catch {
    redirect(`/login?error=service_unavailable&redirect=${encodeURIComponent(`/p/${profileId}`)}`);
  }

  return <>{children}</>;
}
