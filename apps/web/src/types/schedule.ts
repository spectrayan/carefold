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

export type AppointmentStatus =
  | 'requested'
  | 'scheduled'
  | 'confirmed'
  | 'completed'
  | 'cancelled';

export interface AppointmentItem {
  id: string;
  profile_id: string;
  title: string;
  provider_name: string | null;
  specialty: string | null;
  location: string | null;
  clinic_phone: string | null;
  start_time: string; // ISO-8601 UTC
  end_time: string; // ISO-8601 UTC
  timezone: string; // IANA timezone identifier (e.g. America/New_York)
  status: AppointmentStatus;
  reason: string | null;
  preparation_notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppointmentListResponse {
  appointments: AppointmentItem[];
  total: number;
  followup_prompts?: Array<{
    appointment_id: string;
    title: string;
    prompt: string;
  }>;
}

export interface DraftBookingPayload {
  title: string;
  provider_name: string;
  specialty: string;
  clinic_phone: string;
  reason: string;
  insurance_name?: string;
  insurance_member_id?: string;
  insurance_group_number?: string;
  preferred_days?: string[];
  preferred_time_of_day?: 'Morning' | 'Afternoon' | 'Anytime';
  visit_mode?: 'in-person' | 'telehealth';
  tentative_start_time?: string;
  tentative_end_time?: string;
}

export interface DraftBookingResponse {
  appointment: AppointmentItem;
  phone_script: string;
  portal_draft: string;
  checklist: string[];
}

export type ReminderCategory =
  | 'medication'
  | 'vitals'
  | 'appointment'
  | 'prep'
  | 'general';

export type ReminderStatus =
  | 'pending'
  | 'completed'
  | 'snoozed'
  | 'missed'
  | 'cancelled';

export interface ReminderItem {
  id: string;
  profile_id: string;
  title: string;
  description: string | null;
  category: ReminderCategory;
  rrule: string | null; // RFC 5545 recurrence rule
  timezone: string;
  next_due_at: string; // ISO-8601 UTC
  status: ReminderStatus;
  last_triggered_at: string | null;
  snooze_until: string | null; // ISO-8601 UTC
  job_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReminderListResponse {
  reminders: ReminderItem[];
  total: number;
}

export type SnoozeInterval = '+15m' | '+1h' | '+24h';
