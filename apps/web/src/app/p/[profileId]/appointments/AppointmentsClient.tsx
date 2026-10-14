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

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Calendar as CalendarIcon,
  Download,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import { Segmented } from '@/components/ui/Segmented';
import {
  AppointmentCard,
  HowToBookSheet,
  RemindersChecklist,
} from '@/components/appointments';
import {
  fetchAppointments,
  fetchReminders,
  updateAppointment,
  deleteAppointment,
  updateReminder,
  snoozeReminder,
  deleteReminder,
  downloadCalendarIcs,
} from '@/lib/scheduleApi';
import type {
  AppointmentItem,
  ReminderItem,
  SnoozeInterval,
} from '@/types/schedule';
import { useI18n } from '@/i18n';

export interface AppointmentsClientProps {
  profileId: string;
}

export function AppointmentsClient({ profileId }: AppointmentsClientProps) {
  const { t } = useI18n();
  const [appointments, setAppointments] = useState<AppointmentItem[]>([]);
  const [reminders, setReminders] = useState<ReminderItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Mobile segmented view mode: 'visits' vs 'reminders'
  const [mobileView, setMobileView] = useState<'visits' | 'reminders'>('visits');

  // How to book sheet state
  const [bookingSheetAppointment, setBookingSheetAppointment] = useState<AppointmentItem | null>(null);

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [apptRes, remRes] = await Promise.all([
        fetchAppointments(profileId),
        fetchReminders(profileId),
      ]);
      setAppointments(apptRes.appointments || []);
      setReminders(remRes.reminders || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load appointments and reminders.');
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [profileId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = () => {
    setIsRefreshing(true);
    loadData();
  };

  const handleDownloadCalendar = async () => {
    try {
      await downloadCalendarIcs(profileId, { sanitizePhi: true });
    } catch (err: any) {
      setError(err.message || 'Failed to export calendar.');
    }
  };

  const handleCancelAppointment = async (appointmentId: string) => {
    try {
      await deleteAppointment(profileId, appointmentId, false);
      setAppointments((prev) =>
        prev.map((a) => (a.id === appointmentId ? { ...a, status: 'cancelled' } : a))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to cancel appointment.');
    }
  };

  const handleConfirmAppointment = async (appointmentId: string) => {
    try {
      const updated = await updateAppointment(profileId, appointmentId, { status: 'confirmed' });
      setAppointments((prev) =>
        prev.map((a) => (a.id === appointmentId ? updated : a))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to confirm appointment.');
    }
  };

  const handleCompleteReminder = async (reminderId: string) => {
    try {
      const updated = await updateReminder(profileId, reminderId, { status: 'completed' });
      setReminders((prev) =>
        prev.map((r) => (r.id === reminderId ? updated : r))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to mark reminder complete.');
    }
  };

  const handleSnoozeReminder = async (reminderId: string, interval: SnoozeInterval) => {
    try {
      const updated = await snoozeReminder(profileId, reminderId, interval);
      setReminders((prev) =>
        prev.map((r) => (r.id === reminderId ? updated : r))
      );
    } catch (err: any) {
      setError(err.message || 'Failed to snooze reminder.');
    }
  };

  const handleDeleteReminder = async (reminderId: string) => {
    try {
      await deleteReminder(profileId, reminderId, true);
      setReminders((prev) => prev.filter((r) => r.id !== reminderId));
    } catch (err: any) {
      setError(err.message || 'Failed to delete reminder.');
    }
  };

  // Sort upcoming appointments ascending by start_time
  const sortedAppointments = [...appointments].sort(
    (a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  );

  return (
    <div className="space-y-6">
      {/* Top Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-[var(--cf-border)]">
        <div>
          <h1
            data-testid="schedule-page-heading"
            className="text-2xl font-bold tracking-tight text-[var(--cf-fg)] flex items-center gap-2.5"
          >
            <CalendarIcon className="w-6 h-6 text-blue-500" />
            {t('schedule.title')}
          </h1>
          <p className="text-xs sm:text-sm text-[var(--cf-fg-muted)] mt-1">
            {t('schedule.subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          {/* Download RFC 5545 .ics Calendar */}
          <button
            type="button"
            data-testid="export-calendar-ics-btn"
            onClick={handleDownloadCalendar}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-semibold text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[40px]"
            title="Download .ics Calendar (RFC 5545)"
          >
            <Download className="w-4 h-4 text-emerald-600" />
            <span>{t('schedule.download_ics')}</span>
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[40px] min-w-[40px] flex items-center justify-center"
            title="Refresh schedule"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-300 dark:border-rose-900 text-rose-800 dark:text-rose-200 text-xs">
          {error}
        </div>
      )}

      {/* Mobile Switcher (< lg) */}
      <div className="block lg:hidden">
        <Segmented
          aria-label="Mobile schedule view switcher"
          value={mobileView}
          onChange={(val) => setMobileView(val as any)}
          options={[
            { label: t('schedule.visits_tab', { count: appointments.length }), value: 'visits' },
            { label: t('schedule.reminders_tab', { count: reminders.filter((r) => r.status !== 'completed').length }), value: 'reminders' },
          ]}
        />
      </div>

      {isLoading ? (
        <div className="py-20 flex flex-col items-center justify-center gap-3 text-[var(--cf-fg-subtle)]">
          <Loader2 className="w-8 h-8 animate-spin text-[var(--cf-primary)]" />
          <p className="text-sm">{t('schedule.loading')}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Appointments (Visible on desktop OR mobile 'visits') */}
          <div
            className={`space-y-4 lg:col-span-7 ${
              mobileView === 'visits' ? 'block' : 'hidden lg:block'
            }`}
          >
            <div className="flex items-center justify-between pb-2 border-b border-[var(--cf-border)]">
              <h2 className="font-semibold text-sm text-[var(--cf-fg)] uppercase tracking-wider">
                {t('schedule.upcoming_visits', { count: sortedAppointments.length })}
              </h2>
            </div>

            {sortedAppointments.length === 0 ? (
              <div
                data-testid="appointments-empty"
                className="py-12 text-center text-sm text-[var(--cf-fg-subtle)] border-dashed border-2 border-[var(--cf-border)] rounded-2xl p-6"
              >
                <CalendarIcon className="w-8 h-8 mx-auto text-[var(--cf-fg-subtle)] mb-2 opacity-50" />
                <p className="font-medium text-[var(--cf-fg-muted)]">{t('schedule.no_upcoming_visits')}</p>
                <p className="text-xs mt-0.5">
                  {t('schedule.no_upcoming_visits_desc')}
                </p>
              </div>
            ) : (
              <div data-testid="appointments-list" className="space-y-3.5">
                {sortedAppointments.map((appt) => (
                  <AppointmentCard
                    key={appt.id}
                    appointment={appt}
                    profileId={profileId}
                    onOpenHowToBook={(a) => setBookingSheetAppointment(a)}
                    onCancelAppointment={handleCancelAppointment}
                    onConfirmAppointment={handleConfirmAppointment}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Right Column: Reminders (Visible on desktop OR mobile 'reminders') */}
          <div
            className={`space-y-4 lg:col-span-5 ${
              mobileView === 'reminders' ? 'block' : 'hidden lg:block'
            }`}
          >
            <RemindersChecklist
              reminders={reminders}
              profileId={profileId}
              onCompleteReminder={handleCompleteReminder}
              onSnoozeReminder={handleSnoozeReminder}
              onDeleteReminder={handleDeleteReminder}
            />
          </div>
        </div>
      )}

      {/* "How to Book" Slide-Over Sheet */}
      <HowToBookSheet
        isOpen={Boolean(bookingSheetAppointment)}
        onOpenChange={(open) => !open && setBookingSheetAppointment(null)}
        appointment={bookingSheetAppointment}
        onConfirmBooking={(id) => handleConfirmAppointment(id)}
      />
    </div>
  );
}
