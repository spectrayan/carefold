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
import {
  Phone,
  Copy,
  Check,
  CheckCircle2,
  ShieldCheck,
} from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from '@/components/ui/Sheet';
import { Button } from '@/components/ui/Button';
import type { AppointmentItem } from '@/types/schedule';

export interface HowToBookSheetProps {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  appointment?: AppointmentItem | null;
  onConfirmBooking?: (appointmentId: string, confirmedData?: { start_time?: string; end_time?: string; location?: string }) => void;
}

export function HowToBookSheet({
  isOpen,
  onOpenChange,
  appointment,
  onConfirmBooking,
}: HowToBookSheetProps) {
  const [activeTab, setActiveTab] = useState<'phone' | 'portal'>('phone');
  const [copied, setCopied] = useState(false);
  const [checklistState, setChecklistState] = useState<Record<number, boolean>>({});

  if (!appointment) return null;

  const provider = appointment.provider_name || 'the healthcare provider';
  const specialty = appointment.specialty || 'General Practice';
  const reason = appointment.reason || appointment.title || 'clinical consultation';
  const phone = appointment.clinic_phone;

  // 5-Point Insurance Checklist Items
  const checklistItems = [
    'Verify in-network coverage with insurance plan',
    'Obtain PCP referral if required by plan rules',
    'Prepare current medication list and recent vitals log',
    'Bring photo ID and current insurance card',
    'Confirm clinic arrival time (typically 15–30 min prior)',
  ];

  const portalDraft = `Subject: Appointment Request — ${reason}

Dear ${provider} Care Team,

I would like to request an appointment regarding ${reason}.
Please let me know your earliest available dates and times. My preference is for morning consultations.

Thank you,
Carefold Patient`;

  const handleCopyPortalDraft = async () => {
    try {
      await navigator.clipboard.writeText(portalDraft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // fallback
    }
  };

  const toggleChecklistItem = (idx: number) => {
    setChecklistState((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <Sheet open={isOpen} onOpenChange={onOpenChange} side="right">
      <SheetContent data-testid="how-to-book-sheet" className="w-full sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Phone className="w-5 h-5 text-[var(--cf-primary)]" />
            How to Book Consultation
          </SheetTitle>
          <SheetDescription>
            {provider} · {specialty}
            {phone && ` · ${phone}`}
          </SheetDescription>
        </SheetHeader>

        {/* Tab switcher: Phone script vs Portal message */}
        <div className="flex border-b border-[var(--cf-border)] mt-4">
          <button
            type="button"
            data-testid="tab-phone-script"
            onClick={() => setActiveTab('phone')}
            className={`py-2 px-4 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === 'phone'
                ? 'border-[var(--cf-primary)] text-[var(--cf-primary)]'
                : 'border-transparent text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
            }`}
          >
            Phone Call Script
          </button>
          <button
            type="button"
            data-testid="tab-portal-draft"
            onClick={() => setActiveTab('portal')}
            className={`py-2 px-4 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === 'portal'
                ? 'border-[var(--cf-primary)] text-[var(--cf-primary)]'
                : 'border-transparent text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
            }`}
          >
            Portal Message Draft
          </button>
        </div>

        {activeTab === 'phone' ? (
          <div data-testid="phone-script-content" className="space-y-4 py-4 text-xs">
            {/* 1. GREETING */}
            <div className="p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] space-y-1">
              <span className="font-bold text-[11px] uppercase tracking-wider text-[var(--cf-fg-subtle)]">
                1. Greeting
              </span>
              <p className="text-[var(--cf-fg)] text-sm font-medium">
                &ldquo;Hello, I would like to schedule an appointment with {provider} ({specialty}).&rdquo;
              </p>
            </div>

            {/* 2. REASON */}
            <div className="p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] space-y-1">
              <span className="font-bold text-[11px] uppercase tracking-wider text-[var(--cf-fg-subtle)]">
                2. Reason for Visit
              </span>
              <p className="text-[var(--cf-fg)] text-sm font-medium">
                &ldquo;I am calling regarding {reason}.&rdquo;
              </p>
            </div>

            {/* 3. INSURANCE CHECKLIST */}
            <div className="p-3 rounded-xl border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50/50 dark:bg-emerald-950/20 space-y-2">
              <div className="flex items-center gap-1.5 text-emerald-800 dark:text-emerald-300 font-bold text-xs">
                <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-600" />
                <span>3. 5-Point Insurance Checklist</span>
              </div>
              <ul className="space-y-1.5 pt-1">
                {checklistItems.map((item, idx) => (
                  <li
                    key={idx}
                    data-testid={`checklist-item-${idx}`}
                    onClick={() => toggleChecklistItem(idx)}
                    className="flex items-start gap-2 cursor-pointer select-none text-[var(--cf-fg)]"
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(checklistState[idx])}
                      onChange={() => toggleChecklistItem(idx)}
                      className="mt-0.5 rounded text-[var(--cf-primary)] focus:ring-[var(--cf-focus)]"
                    />
                    <span className={checklistState[idx] ? 'line-through text-[var(--cf-fg-subtle)]' : ''}>
                      {item}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* 4. AVAILABILITY */}
            <div className="p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] space-y-1">
              <span className="font-bold text-[11px] uppercase tracking-wider text-[var(--cf-fg-subtle)]">
                4. Availability Preference
              </span>
              <p className="text-[var(--cf-fg)] text-sm font-medium">
                &ldquo;What is the earliest available opening for an in-person or telehealth consultation?&rdquo;
              </p>
            </div>

            {/* 5. CONFIRMATION */}
            <div className="p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] space-y-1">
              <span className="font-bold text-[11px] uppercase tracking-wider text-[var(--cf-fg-subtle)]">
                5. Confirmation
              </span>
              <p className="text-[var(--cf-fg)] text-sm font-medium">
                &ldquo;Please confirm the clinic address, arrival time, and any required intake forms.&rdquo;
              </p>
            </div>
          </div>
        ) : (
          <div data-testid="portal-draft-content" className="space-y-4 py-4">
            <div className="relative">
              <textarea
                data-testid="portal-draft-textarea"
                readOnly
                value={portalDraft}
                rows={9}
                className="w-full p-3 font-mono text-xs rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg)] leading-relaxed resize-none focus:outline-none"
              />
              <button
                type="button"
                data-testid="copy-portal-draft-btn"
                onClick={handleCopyPortalDraft}
                className="absolute top-2.5 right-2.5 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] hover:bg-[var(--cf-surface-2)] text-xs font-semibold text-[var(--cf-fg)] shadow-sm transition-colors"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span>Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-[var(--cf-fg-muted)]" />
                    <span>Copy Text</span>
                  </>
                )}
              </button>
            </div>
            <div aria-live="polite" className="sr-only">
              {copied ? 'Message text copied to clipboard' : ''}
            </div>
          </div>
        )}

        <SheetFooter className="pt-4 border-t border-[var(--cf-border)] flex flex-col sm:flex-row gap-2">
          {phone && (
            <a
              data-testid="how-to-book-call-btn"
              href={`tel:${phone}`}
              className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface)] hover:bg-[var(--cf-surface-2)] text-xs font-semibold text-[var(--cf-fg)] transition-colors"
            >
              <Phone className="w-4 h-4 text-emerald-600" />
              Call {phone}
            </a>
          )}
          {onConfirmBooking && (
            <Button
              type="button"
              data-testid="sheet-confirm-booking-btn"
              onClick={() => {
                onConfirmBooking(appointment.id);
                onOpenChange(false);
              }}
              className="w-full sm:w-auto text-xs"
            >
              <CheckCircle2 className="w-4 h-4 mr-1.5" />
              Mark as Confirmed
            </Button>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
