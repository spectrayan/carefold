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

import React, { useState } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Calendar,
  AlertTriangle,
  Globe,
  Hash,
  Terminal,
  Smartphone,
  QrCode,
  CheckCircle2,
  Search,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type {
  AuditChainVerificationResponse,
  OsServiceDescriptorItem,
  SmartHealthCardVerificationResult,
  SmartSchedulingSlotItem,
  V2ConnectorSummary,
  ZocdocBookingPreview,
} from '@/types/coordinatedCare';
import type {
  DiscoverSmartSchedulingSlotsPayload,
  PreviewZocdocBookingPayload,
  VerifySmartHealthCardPayload,
} from '@/lib/coordinatedCareClient';

export interface CoordinatedV2PanelProps {
  shcResult?: SmartHealthCardVerificationResult | null;
  smartSlots?: SmartSchedulingSlotItem[];
  zocdocPreview?: ZocdocBookingPreview | null;
  v2Connectors?: V2ConnectorSummary[];
  auditVerification?: AuditChainVerificationResponse | null;
  serviceDescriptors?: OsServiceDescriptorItem[];
  onVerifySmartHealthCard?: (
    payload: VerifySmartHealthCardPayload
  ) => void | Promise<void>;
  onDiscoverSmartSlots?: (
    payload: DiscoverSmartSchedulingSlotsPayload
  ) => void | Promise<void>;
  onRequestZocdocApproval?: (
    payload: PreviewZocdocBookingPayload
  ) => void | Promise<void>;
  onVerifyAuditChain?: () => void | Promise<void>;
  className?: string;
}

function getPlatformDisplayLabel(
  platform: OsServiceDescriptorItem['platform']
): string {
  switch (platform) {
    case 'macos_launchd':
      return 'macOS launchd';
    case 'linux_systemd':
      return 'Linux systemd --user';
    case 'windows_task_scheduler':
      return 'Windows Task Scheduler';
  }
}

export function CoordinatedV2Panel({
  shcResult = null,
  smartSlots = [],
  zocdocPreview = null,
  v2Connectors = [],
  auditVerification = null,
  serviceDescriptors = [],
  onVerifySmartHealthCard,
  onDiscoverSmartSlots,
  onRequestZocdocApproval,
  onVerifyAuditChain,
  className,
}: CoordinatedV2PanelProps) {
  const [shcFilename, setShcFilename] = useState(
    'immunization.smart-health-card'
  );
  const [shcContent, setShcContent] = useState('shc:/5676290952432060346029');
  const [specialtyFilter, setSpecialtyFilter] = useState('pediatrics');

  const handleVerifyShc = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!shcContent.trim()) return;
    await onVerifySmartHealthCard?.({
      filename: shcFilename.trim() || 'record.smart-health-card',
      content: shcContent.trim(),
    });
  };

  const handleDiscoverSlots = async (e: React.FormEvent) => {
    e.preventDefault();
    await onDiscoverSmartSlots?.({
      specialty: specialtyFilter.trim() || undefined,
    });
  };

  return (
    <div
      data-testid="coordinated-v2-panel"
      className={cn('space-y-8', className)}
    >
      {/* Section 1: SMART Health Card (.smart-health-card / shc:/) JWS Verifier (AU-77) */}
      <section
        data-testid="shc-verifier-section"
        className="space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              SMART Health Card (<code>.smart-health-card</code> /{' '}
              <code>shc:/</code>) JWS Verifier
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Verifies compact JWS ES256 cryptographic signatures and raw DEFLATE FHIR bundles before staging into your local profile.
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60">
            <QrCode className="w-3.5 h-3.5 shrink-0" />
            JWS ES256 + Raw DEFLATE
          </span>
        </div>

        <Card className="p-4 space-y-4 border border-[var(--cf-border)] shadow-sm">
          <form
            data-testid="shc-verify-form"
            onSubmit={handleVerifyShc}
            className="space-y-3"
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label
                  htmlFor="shc-filename-input"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Source Filename
                </label>
                <input
                  id="shc-filename-input"
                  type="text"
                  data-testid="shc-filename-input"
                  value={shcFilename}
                  onChange={(e) => setShcFilename(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div className="md:col-span-2">
                <label
                  htmlFor="shc-payload-input"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  Paste <code>.smart-health-card</code> JSON or{' '}
                  <code>shc:/</code> QR URI
                </label>
                <textarea
                  id="shc-payload-input"
                  rows={2}
                  data-testid="shc-payload-input"
                  value={shcContent}
                  onChange={(e) => setShcContent(e.target.value)}
                  className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>
            </div>

            <div className="flex justify-end">
              <Button
                type="submit"
                size="sm"
                variant="primary"
                data-testid="shc-verify-submit-btn"
                leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
              >
                Verify &amp; Stage SMART Health Card
              </Button>
            </div>
          </form>

          {shcResult && (
            <div
              data-testid="shc-verification-result"
              className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-2 text-xs"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    data-testid="shc-verification-badge"
                    className={cn(
                      'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border',
                      shcResult.verification_status === 'verified'
                        ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                        : shcResult.verification_status === 'unverified_issuer'
                          ? 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
                          : 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60'
                    )}
                  >
                    {shcResult.verification_status === 'verified' ? (
                      <>
                        <CheckCircle2 className="w-3 h-3 shrink-0" />
                        ES256 Signature Verified
                      </>
                    ) : shcResult.verification_status === 'unverified_issuer' ? (
                      <>
                        <AlertTriangle className="w-3 h-3 shrink-0" />
                        Unverified Issuer
                      </>
                    ) : (
                      <>
                        <ShieldAlert className="w-3 h-3 shrink-0" />
                        Invalid JWS Signature
                      </>
                    )}
                  </span>
                  <span
                    data-testid="shc-issuer-uri"
                    className="font-mono text-xs text-[var(--cf-fg-muted)]"
                  >
                    Issuer: {shcResult.issuer}
                  </span>
                </div>

                <span
                  data-testid="shc-summary-counts"
                  className="text-xs font-semibold text-[var(--cf-fg)]"
                >
                  Staged: {shcResult.summary.immunisations} immunisations,{' '}
                  {shcResult.summary.observations} observations
                </span>
              </div>

              {shcResult.staged_records.length > 0 && (
                <div
                  data-testid="shc-staged-records-list"
                  className="space-y-1 pt-1"
                >
                  {shcResult.staged_records.map((rec, idx) => (
                    <div
                      key={`${rec.resource_type}-${idx}`}
                      className="flex flex-wrap items-center justify-between gap-2 px-2.5 py-1.5 rounded bg-[var(--cf-surface)] border border-[var(--cf-border)]"
                    >
                      <span className="font-medium text-[var(--cf-fg)]">
                        {rec.display} ({rec.resource_type})
                      </span>
                      <span className="text-xs font-mono text-[var(--cf-fg-muted)]">
                        {rec.source_display}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </section>

      {/* Section 2: Coordinated Scheduling: SMART Scheduling Links & Zocdoc Booking (AU-71 & AU-72) */}
      <section
        data-testid="coordinated-scheduling-section"
        className="space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Coordinated Scheduling: SMART Scheduling Links &amp; Zocdoc Booking
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Cross-checks public SMART Scheduling Links availability against your local calendar; external Zocdoc bookings enforce per-booking human approval.
            </p>
          </div>
          <span
            data-testid="zocdoc-irreversible-badge"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800/60"
          >
            <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
            Irreversible Action — Per-Booking Human Approval Required (Even in A2)
          </span>
        </div>

        <Card className="p-4 space-y-4 border border-[var(--cf-border)] shadow-sm">
          <form
            data-testid="discover-smart-slots-form"
            onSubmit={handleDiscoverSlots}
            className="flex flex-wrap items-end justify-between gap-3"
          >
            <div className="flex-1 min-w-[200px]">
              <label
                htmlFor="smart-slots-specialty-input"
                className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
              >
                Specialty Filter
              </label>
              <input
                id="smart-slots-specialty-input"
                type="text"
                data-testid="smart-slots-specialty-input"
                value={specialtyFilter}
                onChange={(e) => setSpecialtyFilter(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>

            <Button
              type="submit"
              size="sm"
              variant="secondary"
              data-testid="discover-smart-slots-btn"
              leftIcon={<Search className="w-3.5 h-3.5" />}
            >
              Discover SMART Scheduling Slots
            </Button>
          </form>

          {smartSlots.length === 0 ? (
            <div
              data-testid="smart-slots-empty"
              className="p-3 rounded-lg bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-xs text-[var(--cf-fg-muted)]"
            >
              No SMART Scheduling Links or Zocdoc slots loaded yet.
            </div>
          ) : (
            <div
              data-testid="smart-slots-list"
              className="space-y-3"
            >
              {smartSlots.map((slot) => (
                <div
                  key={slot.slot_id}
                  data-testid={`smart-slot-card-${slot.slot_id}`}
                  className="p-3 rounded-xl border border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex flex-wrap items-center justify-between gap-3"
                >
                  <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Calendar className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                      <h4 className="text-xs font-bold text-[var(--cf-fg)]">
                        {slot.provider_name} — {slot.specialty}
                      </h4>
                      <span
                        data-testid={`smart-slot-calendar-badge-${slot.slot_id}`}
                        className={cn(
                          'px-2 py-0.5 rounded-full text-xs font-semibold border',
                          slot.fits_calendar
                            ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                            : 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
                        )}
                      >
                        {slot.fits_calendar ? 'Fits Calendar' : 'Calendar Conflict'}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-[var(--cf-surface)] border border-[var(--cf-border)] text-xs font-mono text-[var(--cf-fg-muted)]">
                        {slot.source}
                      </span>
                    </div>
                    <p className="text-xs font-mono text-[var(--cf-fg-muted)]">
                      {slot.location} • {slot.start_time} → {slot.end_time}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="primary"
                      data-testid={`zocdoc-request-approval-btn-${slot.slot_id}`}
                      onClick={() =>
                        onRequestZocdocApproval?.({
                          provider_id: `prov-${slot.slot_id}`,
                          provider_name: slot.provider_name,
                          specialty: slot.specialty,
                          slot_id: slot.slot_id,
                          start_time: slot.start_time,
                        })
                      }
                    >
                      Request Booking Approval
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {zocdocPreview && (
            <div
              data-testid="zocdoc-booking-preview-card"
              className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 border border-rose-200 dark:border-rose-800/60 space-y-1.5 text-xs text-rose-900 dark:text-rose-200"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold">
                  Zocdoc Booking Staged for Approval: {zocdocPreview.provider_name} (
                  {zocdocPreview.specialty})
                </span>
                <span className="px-2 py-0.5 rounded text-xs font-mono font-bold uppercase bg-rose-100 dark:bg-rose-900/50 border border-rose-300 dark:border-rose-700">
                  Risk Tier: {zocdocPreview.risk_tier} • {zocdocPreview.status}
                </span>
              </div>
              <p
                data-testid="zocdoc-preview-hash"
                className="text-xs font-mono text-rose-800 dark:text-rose-300"
              >
                Payload SHA-256: {zocdocPreview.payload_hash}
              </p>
            </div>
          )}
        </Card>
      </section>

      {/* Section 3: Expanded v2 EHR, Payer & Wearable Connectors (AU-73, AU-74, AU-75) */}
      <section
        data-testid="v2-connectors-catalog-section"
        className="space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Expanded v2 EHR, Payer &amp; Wearable Connectors
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Supports Oracle Health (SMART R4), athenahealth (SMART R4), CMS Blue Button 2.0 (EOB Claims), Oura Ring (Daily Sleep/HRV), Google Health Connect, and Microsoft Graph Calendar.
            </p>
          </div>
          <span
            data-testid="android-health-connect-companion-badge"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/60"
          >
            <Smartphone className="w-3.5 h-3.5 shrink-0" />
            Android Health Connect Companion
          </span>
        </div>

        {v2Connectors.length === 0 ? (
          <Card
            data-testid="v2-connectors-empty"
            className="p-4 text-xs text-[var(--cf-fg-muted)] border border-[var(--cf-border)] shadow-sm"
          >
            No v2 connectors loaded. Available v2 manifests include Oracle Health (SMART R4), athenahealth (SMART R4), CMS Blue Button 2.0 (EOB Claims), Oura Ring (Daily Sleep/HRV), Google Health Connect, and Microsoft Graph Calendar.
          </Card>
        ) : (
          <div
            data-testid="v2-connectors-grid"
            className="grid grid-cols-1 md:grid-cols-3 gap-4"
          >
            {v2Connectors.map((conn) => (
              <Card
                key={conn.id}
                data-testid={`v2-connector-card-${conn.id}`}
                className="p-4 space-y-2.5 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                      {conn.name}
                    </h4>
                    <span className="text-xs font-mono text-[var(--cf-fg-muted)]">
                      {conn.id} • {conn.category}
                    </span>
                  </div>
                  <span
                    className={cn(
                      'px-2 py-0.5 rounded text-xs font-semibold border',
                      conn.trust_level === 'trusted'
                        ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                        : 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
                    )}
                  >
                    {conn.trust_level} ({conn.risk_tier})
                  </span>
                </div>

                <div className="flex flex-wrap gap-1 pt-1">
                  {conn.allowed_hosts.map((host) => (
                    <span
                      key={host}
                      className="inline-flex items-center gap-1 text-xs font-mono text-[var(--cf-fg-muted)]"
                    >
                      <Globe className="w-2.5 h-2.5 text-emerald-600 shrink-0" />
                      {host}
                    </span>
                  ))}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Section 4: Tamper-Evident Audit Hash Chain & OS Daemon Service Packaging (AU-78 & AU-81) */}
      <section
        data-testid="audit-and-os-service-section"
        className="space-y-4"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              Tamper-Evident Audit Hash Chain &amp; OS Daemon Service Packaging
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Verify your profile&apos;s append-only SHA-256 audit log chain and inspect loopback-bound background daemon descriptors.
            </p>
          </div>
          <span
            data-testid="os-service-loopback-notice"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
          >
            <Terminal className="w-3.5 h-3.5 shrink-0" />
            Bound Strictly to 127.0.0.1 Loopback
          </span>
        </div>

        {/* Audit Hash Chain Verification Card */}
        <Card className="p-4 space-y-3 border border-[var(--cf-border)] shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-[var(--cf-fg-muted)]">
                  SHA-256 Audit Log Hash Chain
                </h4>
                {auditVerification && (
                  <span
                    data-testid="audit-chain-status-badge"
                    className={cn(
                      'inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border',
                      auditVerification.valid
                        ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                        : 'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60'
                    )}
                  >
                    {auditVerification.valid ? (
                      <>
                        <ShieldCheck className="w-3 h-3 shrink-0" />
                        Chain Intact
                      </>
                    ) : (
                      <>
                        <ShieldAlert className="w-3 h-3 shrink-0" />
                        Tamper Detected at Event{' '}
                        {auditVerification.broken_at_event_id ?? 'unknown'}
                      </>
                    )}
                  </span>
                )}
              </div>

              {auditVerification ? (
                <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-[var(--cf-fg-muted)]">
                  <span data-testid="audit-chain-checked-count">
                    Checked events: {auditVerification.checked_count}
                  </span>
                  <span
                    data-testid="audit-chain-head-hash"
                    className="inline-flex items-center gap-1"
                  >
                    <Hash className="w-3 h-3 text-emerald-600 shrink-0" />
                    Head: {auditVerification.head_hash ?? 'GENESIS'}
                  </span>
                  {!auditVerification.valid && auditVerification.reason && (
                    <span
                      data-testid="audit-chain-broken-reason"
                      className="text-rose-600 dark:text-rose-400 font-semibold"
                    >
                      Reason: {auditVerification.reason}
                    </span>
                  )}
                </div>
              ) : (
                <p className="text-xs text-[var(--cf-fg-muted)]">
                  Run a cryptographic audit chain check to verify `prev_hash` and `entry_hash` links from GENESIS.
                </p>
              )}
            </div>

            <Button
              type="button"
              size="sm"
              variant="primary"
              data-testid="verify-audit-chain-btn"
              leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
              onClick={() => onVerifyAuditChain?.()}
            >
              Verify Audit Chain
            </Button>
          </div>
        </Card>

        {/* OS Background Service Descriptors */}
        {serviceDescriptors.length > 0 && (
          <div
            data-testid="os-service-descriptors-grid"
            className="grid grid-cols-1 md:grid-cols-3 gap-4"
          >
            {serviceDescriptors.map((desc) => (
              <Card
                key={desc.platform}
                data-testid={`os-service-card-${desc.platform}`}
                className="p-4 space-y-2 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <h4 className="text-xs font-bold text-[var(--cf-fg)]">
                    {getPlatformDisplayLabel(desc.platform)}
                  </h4>
                  <span className="text-xs font-mono text-[var(--cf-fg-muted)]">
                    {desc.filename}
                  </span>
                </div>
                <p className="text-xs font-mono text-[var(--cf-fg-muted)] break-all">
                  Path: {desc.install_path}
                </p>
                <div
                  data-testid={`os-service-cmd-${desc.platform}`}
                  className="p-2 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-xs font-mono text-[var(--cf-fg)] break-all"
                >
                  {desc.install_command}
                </div>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
