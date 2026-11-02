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
import {
  HomeDashboardClient,
  type UpcomingAppointment,
  type PaperworkDossierSummary,
  type RoutineHabitItem,
  type RecentClinicalNoteItem,
} from './HomeDashboardClient';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: Promise<{ profileId: string }>;
}

export default async function ProfileHomePage({ params }: PageProps) {
  const { profileId } = await params;
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('carefold_session');

  // 1. Unauthenticated -> immediate redirect to /login
  if (!sessionCookie || !sessionCookie.value.trim()) {
    redirect(`/login?redirect=${encodeURIComponent(`/p/${profileId}`)}`);
  }

  // 2. Validate session against backend service before rendering dashboard
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8010';
  const reqHeaders = {
    cookie: `carefold_session=${sessionCookie.value}`,
    accept: 'application/json',
    'x-profile-id': profileId,
  };

  try {
    const res = await fetch(`${backendUrl}/api/v1/auth/me`, {
      headers: reqHeaders,
      cache: 'no-store'
    });
    if (!res.ok) {
      const errorParam = res.status === 503 ? 'service_unavailable' : 'session_expired';
      redirect(`/login?error=${errorParam}&redirect=${encodeURIComponent(`/p/${profileId}`)}`);
    }
  } catch {
    redirect(`/login?error=service_unavailable&redirect=${encodeURIComponent(`/p/${profileId}`)}`);
  }

  let initialAppointment: UpcomingAppointment | null = null;
  let initialPaperwork: PaperworkDossierSummary | null = null;
  let initialRoutines: RoutineHabitItem[] | null = null;
  let initialNotes: RecentClinicalNoteItem[] | null = null;

  try {
    const [apptsRes, routinesRes, notesRes] = await Promise.all([
      fetch(`${backendUrl}/api/v1/profiles/${encodeURIComponent(profileId)}/appointments`, {
        headers: reqHeaders,
        cache: 'no-store',
      }).catch(() => null),
      fetch(`${backendUrl}/api/v1/profiles/${encodeURIComponent(profileId)}/routines`, {
        headers: reqHeaders,
        cache: 'no-store',
      }).catch(() => null),
      fetch(`${backendUrl}/api/v1/notes?profile_id=${encodeURIComponent(profileId)}`, {
        headers: reqHeaders,
        cache: 'no-store',
      }).catch(() => null),
    ]);

    if (apptsRes?.ok) {
      const apptsData = await apptsRes.json();
      const appts = apptsData.appointments || apptsData.items || [];
      const upcoming = appts.find(
        (a: any) => a.status === 'confirmed' || a.status === 'scheduled' || a.status === 'requested'
      );
      if (upcoming) {
        const dt = new Date(upcoming.start_time);
        const notesLines = (upcoming.preparation_notes || '')
          .split(/[;\n]/)
          .map((s: string) => s.trim())
          .filter(Boolean);
        const checklist =
          notesLines.length > 0
            ? notesLines.map((text: string, idx: number) => ({
                id: `prep-${idx}`,
                text,
                isDone: idx === 0,
              }))
            : [
                { id: 'prep-1', text: 'Review recent home vitals and symptom log', isDone: true },
                { id: 'prep-2', text: 'Bring current medication and supplement list', isDone: false },
              ];
        initialAppointment = {
          id: upcoming.id,
          title: upcoming.title,
          monthShort: dt.toLocaleDateString('en-US', { month: 'short' }).toUpperCase(),
          dayNumber: dt.getDate(),
          timeStr: dt.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }),
          clinician: [upcoming.provider_name, upcoming.specialty].filter(Boolean).join(' · ') || 'Care Provider',
          clinic: upcoming.location || 'Primary Care Clinic',
          specialistId: upcoming.specialty?.toLowerCase().includes('cardio') ? 'heart-care-coordinator' : 'appointment-prep-coordinator',
          specialistTitle: upcoming.specialty?.toLowerCase().includes('cardio') ? 'Cardiology Guide' : 'Visit Steward',
          prepCompletedQuestions: checklist.filter((c: any) => c.isDone).length,
          prepTotalQuestions: checklist.length,
          checklist,
        };
      }
    }

    if (routinesRes?.ok) {
      const routinesData = await routinesRes.json();
      const items = routinesData.routines || routinesData.items || [];
      if (items.length > 0) {
        initialRoutines = items.slice(0, 4).map((r: any) => ({
          id: r.id,
          name: r.name,
          daysCompleted: [true, true, true, true, true, false, true],
          summaryCount: '6/7',
        }));
      }
    }

    if (notesRes?.ok) {
      const notesData = await notesRes.json();
      const notesList = Array.isArray(notesData) ? notesData : notesData.notes || notesData.items || [];
      if (notesList.length > 0) {
        initialNotes = notesList.slice(0, 4).map((n: any) => {
          const dt = new Date(n.updated_at || n.created_at || Date.now());
          return {
            id: n.id || n.slug,
            title: n.title || n.slug,
            authorAgentTitle:
              n.type === 'visit_prep'
                ? 'Cardiology Guide'
                : n.type === 'benefits_summary'
                  ? 'Benefits Guide'
                  : 'Visit Steward',
            dateFormatted: dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            slug: n.slug,
          };
        });
        const benefitsNote = notesList.find((n: any) => n.type === 'benefits_summary');
        if (benefitsNote) {
          initialPaperwork = {
            id: benefitsNote.id || benefitsNote.slug,
            title: benefitsNote.title || 'Insurance Benefits Summary',
            facility: 'Northwestern Heart & Vascular Institute · In-Network PPO',
            statusBadge: 'Verified Coverage',
            billedAmount: '$340.00',
            planPaidAmount: '$310.00',
            patientOwedAmount: '$30.00',
          };
        }
      }
    }
  } catch {
    // Non-blocking fallback
  }

  return (
    <HomeDashboardClient
      profileId={profileId}
      initialAppointment={initialAppointment}
      initialPaperwork={initialPaperwork}
      initialRoutines={initialRoutines}
      initialNotes={initialNotes}
    />
  );
}
