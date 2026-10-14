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

import React, { useEffect, useRef } from 'react';
import { AlertTriangle, PhoneCall, MapPin, ShieldAlert } from 'lucide-react';
import { DEFAULT_EMERGENCY_SERVICES, EmergencyServicesConfig } from '@/lib/emergency';
import type { ChatMessage } from '@/lib/types';

export interface EmergencyEscalationCardProps {
  message: ChatMessage;
  config?: EmergencyServicesConfig;
}

export function EmergencyEscalationCard({
  message,
  config = DEFAULT_EMERGENCY_SERVICES
}: EmergencyEscalationCardProps) {
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Assertive alert announcement for assistive tech without disruptive viewport jump
    if (cardRef.current) {
      cardRef.current.focus({ preventScroll: true });
    }
  }, []);

  const isCrisis =
    message.emergencyCategory === 'suicide_crisis' ||
    (Boolean(message.refusalReason) && message.refusalReason!.includes('suicide'));

  const RED_FLAG_TITLES: Record<string, string> = {
    bp_crisis_symptomatic: 'Hypertensive Crisis with Symptoms',
    bp_crisis_asymptomatic: 'Severe Blood Pressure Elevation',
    severe_hypoxemia: 'Severe Hypoxemia (Low Oxygen)',
    severe_hypoglycemia: 'Severe Hypoglycemia (Low Blood Sugar)',
    symptomatic_hypotension: 'Symptomatic Hypotension',
    suicide_crisis: 'Suicide & Crisis Support',
    cardiac: 'Acute Symptoms Detected',
    stroke: 'Acute Symptoms Detected',
  };

  const categoryKey = message.emergencyCategory ||
    (message.refusalReason?.replace(/^emergency_red_flag:/, ''));
  const categoryTitle = (categoryKey && RED_FLAG_TITLES[categoryKey]) ||
    (message.refusalReason ? Object.entries(RED_FLAG_TITLES).find(([k]) => message.refusalReason!.includes(k))?.[1] : null);

  return (
    <div
      ref={cardRef}
      tabIndex={-1}
      role="alert"
      aria-live="assertive"
      data-testid="emergency-escalation-card"
      className="relative group flex flex-col my-3 max-w-[95%] md:max-w-[85%] min-w-[280px] rounded-2xl p-5 shadow-sm border-2 border-red-600 bg-red-50/95 dark:bg-red-950/40 text-red-950 dark:text-red-100 focus:outline-none focus:ring-2 focus:ring-red-600 focus:ring-offset-2 dark:focus:ring-offset-zinc-900 transition-colors space-y-3"
    >
      {/* Header Banner */}
      <div className="flex items-center gap-2 pb-2 border-b border-red-200 dark:border-red-900/60 text-red-800 dark:text-red-300 font-bold text-sm">
        <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400 shrink-0" aria-hidden="true" />
        <span data-testid="emergency-card-heading">This may be an emergency</span>
        <span className="ml-auto text-xs font-semibold uppercase px-2 py-0.5 rounded-full bg-red-200 dark:bg-red-900/80 text-red-900 dark:text-red-200">
          Immediate Action Required
        </span>
      </div>

      {/* Red-Flag Category Badge */}
      {categoryTitle && (
        <div data-testid="emergency-category-badge" className="text-xs font-semibold text-red-700 dark:text-red-300 flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-full bg-red-600 animate-ping" />
          <span>Category: {categoryTitle}</span>
        </div>
      )}

      {/* Verbatim Backend Message Callout */}
      <div
        data-testid="emergency-backend-message"
        className="p-3.5 rounded-xl border border-red-300 dark:border-red-900/70 bg-white dark:bg-zinc-900/90 text-sm font-medium text-red-950 dark:text-red-100 shadow-sm leading-relaxed"
      >
        {message.content || 'EMERGENCY WARNING: Acute symptoms detected. Please call 911 or visit the nearest emergency room immediately.'}
      </div>

      {/* Primary & Secondary Emergency Action Links */}
      <div className="flex flex-wrap items-center gap-2.5 pt-1">
        <a
          data-testid="emergency-call-911-btn"
          href={config.primaryEmergency.telUri}
          className="inline-flex items-center gap-2 px-4 py-2.5 min-h-[44px] rounded-xl bg-red-600 hover:bg-red-700 active:bg-red-800 text-white font-bold text-sm shadow-sm transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
        >
          <PhoneCall className="w-4 h-4 shrink-0" aria-hidden="true" />
          <span>{config.primaryEmergency.actionText}</span>
        </a>

        <a
          data-testid="emergency-find-er-btn"
          href={config.erFinderUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 px-4 py-2.5 min-h-[44px] rounded-xl border border-red-600 dark:border-red-400 bg-white dark:bg-zinc-800 hover:bg-red-50 dark:hover:bg-zinc-700 text-red-700 dark:text-red-300 font-semibold text-sm shadow-sm transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
        >
          <MapPin className="w-4 h-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
          <span>{config.erFinderLabel}</span>
        </a>

        {isCrisis && (
          <a
            data-testid="emergency-call-988-btn"
            href={config.crisisLifeline.telUri}
            className="inline-flex items-center gap-2 px-4 py-2.5 min-h-[44px] rounded-xl bg-amber-600 hover:bg-amber-700 active:bg-amber-800 text-white font-bold text-sm shadow-sm transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2"
          >
            <PhoneCall className="w-4 h-4 shrink-0" aria-hidden="true" />
            <span>{config.crisisLifeline.actionText}</span>
          </a>
        )}
      </div>

      {/* Non-Clinical Safety & Boundary Emphasis */}
      <div
        data-testid="emergency-nonclinical-disclaimer"
        className="pt-2 border-t border-red-200 dark:border-red-900/60 text-xs text-red-800 dark:text-red-300/90 leading-relaxed flex items-start gap-1.5"
      >
        <ShieldAlert className="w-3.5 h-3.5 text-red-600 dark:text-red-400 shrink-0 mt-0.5" aria-hidden="true" />
        <span>
          Carefold AI assistants provide educational navigation and visit preparation only. They cannot diagnose conditions, triage acute symptoms, or replace emergency medical personnel.
        </span>
      </div>
    </div>
  );
}

export default EmergencyEscalationCard;
