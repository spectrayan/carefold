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

import type {
  AppointmentItem,
  AppointmentListResponse,
  DraftBookingPayload,
  DraftBookingResponse,
  ReminderItem,
  ReminderListResponse,
  SnoozeInterval,
} from '@/types/schedule';

// ---------------------------------------------------------------------------
// Appointments API
// ---------------------------------------------------------------------------

export async function fetchAppointments(
  profileId: string,
  params?: { status?: string; limit?: number; offset?: number }
): Promise<AppointmentListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.limit) query.set('limit', String(params.limit));
  if (params?.offset) query.set('offset', String(params.offset));

  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/appointments?${query.toString()}`,
    { credentials: 'include' }
  );
  if (!res.ok) throw new Error(`Failed to fetch appointments (${res.status})`);
  return res.json();
}

export async function createAppointment(
  profileId: string,
  payload: Partial<AppointmentItem>
): Promise<AppointmentItem> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/appointments`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create appointment (${res.status})`);
  }
  return res.json();
}

export async function updateAppointment(
  profileId: string,
  appointmentId: string,
  payload: Partial<AppointmentItem>
): Promise<AppointmentItem> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/appointments/${encodeURIComponent(appointmentId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to update appointment (${res.status})`);
  }
  return res.json();
}

export async function deleteAppointment(
  profileId: string,
  appointmentId: string,
  hardDelete = false
): Promise<{ status: string; appointment_id: string }> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/appointments/${encodeURIComponent(appointmentId)}?hard_delete=${hardDelete}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (!res.ok) throw new Error(`Failed to delete appointment (${res.status})`);
  return res.json();
}

export async function draftBookingRequest(
  profileId: string,
  payload: DraftBookingPayload
): Promise<DraftBookingResponse> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/appointments/draft-booking`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to generate booking draft (${res.status})`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Reminders API
// ---------------------------------------------------------------------------

export async function fetchReminders(
  profileId: string,
  params?: { status?: string; category?: string; limit?: number }
): Promise<ReminderListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set('status', params.status);
  if (params?.category) query.set('category', params.category);
  if (params?.limit) query.set('limit', String(params.limit || 50));

  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/reminders?${query.toString()}`,
    { credentials: 'include' }
  );
  if (!res.ok) throw new Error(`Failed to fetch reminders (${res.status})`);
  return res.json();
}

export async function createReminder(
  profileId: string,
  payload: {
    title: string;
    next_due_at: string;
    description?: string;
    category?: string;
    rrule?: string;
    timezone?: string;
  }
): Promise<ReminderItem> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/reminders`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to create reminder (${res.status})`);
  }
  return res.json();
}

export async function updateReminder(
  profileId: string,
  reminderId: string,
  payload: Partial<ReminderItem>
): Promise<ReminderItem> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/reminders/${encodeURIComponent(reminderId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to update reminder (${res.status})`);
  }
  return res.json();
}

export async function snoozeReminder(
  profileId: string,
  reminderId: string,
  interval: SnoozeInterval
): Promise<ReminderItem> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/reminders/${encodeURIComponent(reminderId)}/snooze`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ interval }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to snooze reminder (${res.status})`);
  }
  return res.json();
}

export async function deleteReminder(
  profileId: string,
  reminderId: string,
  hardDelete = false
): Promise<{ status: string; reminder_id: string }> {
  const res = await fetch(
    `/api/profiles/${encodeURIComponent(profileId)}/reminders/${encodeURIComponent(reminderId)}?hard_delete=${hardDelete}`,
    {
      method: 'DELETE',
      credentials: 'include',
    }
  );
  if (!res.ok) throw new Error(`Failed to delete reminder (${res.status})`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Calendar Export Helpers
// ---------------------------------------------------------------------------

export async function downloadCalendarIcs(
  profileId: string,
  options: { sanitizePhi?: boolean; filename?: string } = {}
): Promise<void> {
  const sanitize = options.sanitizePhi ?? true;
  const url = `/api/profiles/${encodeURIComponent(profileId)}/reminders/export.ics?sanitize_phi=${sanitize}`;

  const res = await fetch(url, { credentials: 'include' });
  if (!res.ok) {
    throw new Error('Failed to generate calendar stream');
  }

  const blob = await res.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = downloadUrl;
  anchor.download = options.filename || `carefold_schedule_${profileId}.ics`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(downloadUrl);
}

export function exportSingleAppointmentIcs(appt: AppointmentItem): void {
  const formatIcsDate = (isoStr: string) => {
    const d = new Date(isoStr);
    return d.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '');
  };

  const escapeIcs = (str: string | null) =>
    (str || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');

  const nowStamp = formatIcsDate(new Date().toISOString());
  const startStamp = formatIcsDate(appt.start_time);
  const endStamp = formatIcsDate(appt.end_time);

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Carefold//Carefold Autonomy//EN',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:appt-${appt.id}@carefold.local`,
    `DTSTAMP:${nowStamp}`,
    `DTSTART:${startStamp}`,
    `DTEND:${endStamp}`,
    `SUMMARY:${escapeIcs(appt.title)}`,
    `DESCRIPTION:${escapeIcs(appt.reason || 'Carefold Scheduled Visit')}`,
    appt.location ? `LOCATION:${escapeIcs(appt.location)}` : '',
    'STATUS:CONFIRMED',
    'END:VEVENT',
    'END:VCALENDAR',
  ].filter(Boolean);

  const icsData = lines.join('\r\n');
  const blob = new Blob([icsData], { type: 'text/calendar;charset=utf-8' });
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = downloadUrl;
  anchor.download = `${appt.title.replace(/[^a-zA-Z0-9_-]/g, '_')}.ics`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(downloadUrl);
}

export function humanizeRrule(rruleStr: string | null | undefined, dueIso: string): string {
  if (!rruleStr) {
    const d = new Date(dueIso);
    return `One-time · Due ${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  }

  const clean = rruleStr.replace(/^RRULE:/i, '');
  const parts = Object.fromEntries(
    clean.split(';').map((p) => {
      const [k, v] = p.split('=');
      return [k.toUpperCase(), (v || '').toUpperCase()];
    })
  );

  const timeStr = new Date(dueIso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const interval = parseInt(parts.INTERVAL || '1', 10);
  const freq = parts.FREQ;

  if (freq === 'DAILY') {
    if (interval === 1) return `Every day at ${timeStr}`;
    return `Every ${interval} days at ${timeStr}`;
  }

  if (freq === 'WEEKLY') {
    if (parts.BYDAY) {
      const dayMap: Record<string, string> = {
        MO: 'Mon',
        TU: 'Tue',
        WE: 'Wed',
        TH: 'Thu',
        FR: 'Fri',
        SA: 'Sat',
        SU: 'Sun',
      };
      const days = parts.BYDAY.split(',')
        .map((d) => dayMap[d] || d)
        .join(', ');
      return `Every ${days} at ${timeStr}`;
    }
    if (interval === 1) return `Every week at ${timeStr}`;
    return `Every ${interval} weeks at ${timeStr}`;
  }

  if (freq === 'MONTHLY') {
    return `Monthly at ${timeStr}`;
  }

  return `Repeats: ${clean}`;
}
