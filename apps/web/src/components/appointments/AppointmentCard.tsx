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

'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  MapPin,
  Phone,
  FileText,
  Download,
  CheckCircle2,
  Sparkles,
  BookOpen,
  Calendar,
  X,
  ExternalLink,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';
import type { AppointmentItem, AppointmentStatus } from '@/types/schedule';
import { exportSingleAppointmentIcs } from '@/lib/scheduleApi';

export interface AppointmentCardProps {
  appointment: AppointmentItem;
  profileId: string;
  onOpenHowToBook?: (appointment: AppointmentItem) => void;
  onCancelAppointment?: (appointmentId: string) => void;
  onConfirmAppointment?: (appointmentId: string) => void;
  className?: string;
}

export function AppointmentCard({
  appointment,
  profileId,
  onOpenHowToBook,
  onCancelAppointment,
  onConfirmAppointment,
  className,
}: AppointmentCardProps) {
  const [prepPackLoading, setPrepPackLoading] = useState(false);
  const [prepPackNoteId, setPrepPackNoteId] = useState<string | null>(null);

  const startDate = new Date(appointment.start_time);
  const endDate = new Date(appointment.end_time);

  const monthStr = startDate.toLocaleDateString(undefined, { month: 'short' }).toUpperCase();
  const dayStr = startDate.getDate().toString().padStart(2, '0');
  const timeRangeStr = `${startDate.toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  })} – ${endDate.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;

  const statusVariant = (status: AppointmentStatus) => {
    switch (status) {
      case 'confirmed':
        return 'success';
      case 'scheduled':
        return 'info';
      case 'requested':
        return 'warning';
      case 'completed':
        return 'neutral';
      case 'cancelled':
        return 'danger';
      default:
        return 'neutral';
    }
  };

  const statusLabel = (status: AppointmentStatus) => {
    switch (status) {
      case 'confirmed':
        return 'Confirmed';
      case 'scheduled':
        return 'Scheduled';
      case 'requested':
        return 'Booking Needed';
      case 'completed':
        return 'Completed';
      case 'cancelled':
        return 'Cancelled';
      default:
        return status;
    }
  };

  const isCompleted = appointment.status === 'completed';
  const isCancelled = appointment.status === 'cancelled';
  const isRequested = appointment.status === 'requested';

  const handleGeneratePrepPack = async () => {
    setPrepPackLoading(true);
    try {
      const res = await fetch(`/api/profiles/${encodeURIComponent(profileId)}/prep-pack`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          appointment_id: appointment.id,
          specialty: appointment.specialty,
          visit_reason: appointment.reason,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setPrepPackNoteId(data.note_id || 'generated');
      }
    } catch {
      // fallback
    } finally {
      setPrepPackLoading(false);
    }
  };

  return (
    <Card
      data-testid={`appointment-card-${appointment.id}`}
      className={cn(
        'p-5 transition-all shadow-sm flex flex-col justify-between gap-4',
        isCancelled && 'opacity-60 bg-[var(--cf-surface-2)]/30',
        isCompleted && 'border-slate-300 dark:border-slate-800',
        className
      )}
    >
      {/* Concluded Post-Visit Follow-Up Banner */}
      {isCompleted && (
        <div
          data-testid="post-visit-sweep-banner"
          className="p-3 rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-xs text-[var(--cf-fg)] flex items-start justify-between gap-2"
        >
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
            <span>
              <strong>Visit concluded:</strong> Add after-visit notes to extract prescribed medications and follow-ups.
            </span>
          </div>
          <Link
            href={`/p/${encodeURIComponent(profileId)}/library?type=after_visit`}
            className="text-xs font-semibold text-[var(--cf-primary)] hover:underline shrink-0"
          >
            Add Notes →
          </Link>
        </div>
      )}

      {/* Main Details Row */}
      <div className="flex items-start gap-4">
        {/* Date Tile */}
        <div
          data-testid="appointment-date-tile"
          className={cn(
            'w-14 h-14 rounded-xl flex flex-col items-center justify-center shrink-0 border select-none font-bold',
            appointment.status === 'confirmed'
              ? 'bg-emerald-50 dark:bg-emerald-950/60 border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300'
              : appointment.status === 'requested'
              ? 'bg-amber-50 dark:bg-amber-950/60 border-amber-200 dark:border-amber-900/60 text-amber-700 dark:text-amber-300'
              : appointment.status === 'completed'
              ? 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300'
              : 'bg-blue-50 dark:bg-blue-950/60 border-blue-200 dark:border-blue-900/60 text-blue-700 dark:text-blue-300'
          )}
        >
          <span className="text-[10px] uppercase tracking-wider">{monthStr}</span>
          <span className="text-xl leading-none mt-0.5">{dayStr}</span>
        </div>

        {/* Content Info */}
        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex items-start justify-between gap-2">
            <div>
              <h3
                data-testid="appointment-title"
                className="font-bold text-base text-[var(--cf-fg)] leading-snug"
              >
                {appointment.title}
              </h3>
              {(appointment.provider_name || appointment.specialty) && (
                <p className="text-xs font-medium text-[var(--cf-fg-muted)]">
                  {appointment.provider_name}
                  {appointment.provider_name && appointment.specialty ? ' · ' : ''}
                  {appointment.specialty}
                </p>
              )}
            </div>
            <Badge
              data-testid="appointment-status-badge"
              variant={statusVariant(appointment.status)}
              size="sm"
              className="shrink-0"
            >
              {statusLabel(appointment.status)}
            </Badge>
          </div>

          <div className="text-xs text-[var(--cf-fg-muted)] flex items-center gap-1.5 pt-1">
            <Calendar className="w-3.5 h-3.5 shrink-0 text-[var(--cf-fg-subtle)]" />
            <span data-testid="appointment-time-range">{timeRangeStr}</span>
            <span className="text-[var(--cf-fg-subtle)]">({appointment.timezone})</span>
          </div>

          {/* Location with Google Maps link */}
          {appointment.location && (
            <div className="text-xs text-[var(--cf-fg-muted)] flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 shrink-0 text-[var(--cf-fg-subtle)]" />
              <a
                data-testid="appointment-location-link"
                href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(appointment.location)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-[var(--cf-primary)] hover:underline truncate inline-flex items-center gap-1"
              >
                <span>{appointment.location}</span>
                <ExternalLink className="w-3 h-3 opacity-60" />
              </a>
            </div>
          )}

          {/* Clinic Phone with tel: link */}
          {appointment.clinic_phone && (
            <div className="text-xs text-[var(--cf-fg-muted)] flex items-center gap-1.5">
              <Phone className="w-3.5 h-3.5 shrink-0 text-[var(--cf-fg-subtle)]" />
              <a
                data-testid="appointment-phone-link"
                href={`tel:${appointment.clinic_phone}`}
                className="hover:text-[var(--cf-primary)] hover:underline font-mono"
              >
                {appointment.clinic_phone}
              </a>
            </div>
          )}

          {/* Reason */}
          {appointment.reason && (
            <div className="text-xs text-[var(--cf-fg-subtle)] italic pt-1">
              &ldquo;{appointment.reason}&rdquo;
            </div>
          )}
        </div>
      </div>

      {/* Action Footer */}
      <div className="pt-3 border-t border-[var(--cf-border)] flex flex-wrap items-center justify-between gap-2 text-xs">
        {/* Left: Prep Pack & How to Book Actions */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Prep Pack Button */}
          {prepPackNoteId ? (
            <Link
              href={`/p/${encodeURIComponent(profileId)}/library?noteId=${prepPackNoteId}`}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-[var(--cf-fg)] font-medium hover:bg-[var(--cf-surface)] transition-colors"
            >
              <FileText className="w-3.5 h-3.5 text-teal-600" />
              <span>View Prep Pack</span>
            </Link>
          ) : (
            <button
              type="button"
              data-testid="generate-prep-pack-btn"
              onClick={handleGeneratePrepPack}
              disabled={prepPackLoading}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] hover:bg-[var(--cf-surface-2)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] font-medium transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5 text-teal-500" />
              <span>{prepPackLoading ? 'Generating...' : 'Prep Pack'}</span>
            </button>
          )}

          {/* "How to Book" Script Button (Visible for requested / unconfirmed visits) */}
          {(isRequested || onOpenHowToBook) && (
            <button
              type="button"
              data-testid="how-to-book-trigger-btn"
              onClick={() => onOpenHowToBook?.(appointment)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-amber-300 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 font-semibold transition-colors hover:bg-amber-100"
            >
              <BookOpen className="w-3.5 h-3.5" />
              <span>How to Book</span>
            </button>
          )}

          {/* Quick Mark Confirmed for requested appointments */}
          {isRequested && onConfirmAppointment && (
            <button
              type="button"
              data-testid="mark-confirmed-btn"
              onClick={() => onConfirmAppointment(appointment.id)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold transition-colors"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Confirm Visit</span>
            </button>
          )}
        </div>

        {/* Right: Export .ics & Cancel Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="export-single-ics-btn"
            onClick={() => exportSingleAppointmentIcs(appointment)}
            className="p-1.5 rounded-lg border border-[var(--cf-border)] text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)] transition-colors min-h-[32px] min-w-[32px] flex items-center justify-center"
            title="Download .ics event"
          >
            <Download className="w-3.5 h-3.5" />
          </button>

          {!isCancelled && !isCompleted && onCancelAppointment && (
            <button
              type="button"
              data-testid="cancel-appointment-btn"
              onClick={() => onCancelAppointment(appointment.id)}
              className="p-1.5 rounded-lg text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors min-h-[32px] min-w-[32px] flex items-center justify-center"
              title="Cancel appointment"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
