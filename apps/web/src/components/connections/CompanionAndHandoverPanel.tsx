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
  Smartphone,
  QrCode,
  ShieldCheck,
  KeyRound,
  Lock,
  Trash2,
  UserCheck,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type { ConnectionItem } from '@/types/connections';
import type {
  CompanionDeviceItem,
  CompanionPairingQrPayload,
  TeenHandoverDecision,
  TeenHandoverDecisionMap,
  TeenHandoverPayload,
  TeenHandoverResponse,
  ViewerSectionKey,
} from '@/types/autonomyBatch6';

const ALL_VIEWER_SECTIONS: ViewerSectionKey[] = [
  'vitals',
  'preventive',
  'appointments',
  'reminders',
  'connections',
  'school_forms',
  'notes',
  'documents',
];

export interface CompanionAndHandoverPanelProps {
  companionDevices: CompanionDeviceItem[];
  pairingQr?: CompanionPairingQrPayload | null;
  viewerUserId?: string;
  initialAllowedSections?: ViewerSectionKey[];
  connections: ConnectionItem[];
  handoverResult?: TeenHandoverResponse | null;
  onGeneratePairingQr?: (
    deviceName: string,
    allowedCategories: string[]
  ) => void | Promise<void>;
  onRevokeCompanionDevice?: (deviceId: string) => void | Promise<void>;
  onSaveViewerSections?: (
    viewerUserId: string,
    allowedSections: ViewerSectionKey[]
  ) => void | Promise<void>;
  onExecuteTeenHandover?: (
    payload: TeenHandoverPayload
  ) => void | Promise<void>;
  className?: string;
}

export function CompanionAndHandoverPanel({
  companionDevices,
  pairingQr = null,
  viewerUserId = 'user-grandparent-1',
  initialAllowedSections = ['appointments', 'reminders'],
  connections,
  handoverResult = null,
  onGeneratePairingQr,
  onRevokeCompanionDevice,
  onSaveViewerSections,
  onExecuteTeenHandover,
  className,
}: CompanionAndHandoverPanelProps) {
  const [deviceName, setDeviceName] = useState('iPhone 16 Pro (Apple Health)');
  const [selectedCategories] = useState<string[]>([
    'vitals',
    'clinical_records',
    'reminders',
  ]);

  const [allowedSections, setAllowedSections] = useState<ViewerSectionKey[]>(
    initialAllowedSections
  );

  const [newStewardUserId, setNewStewardUserId] = useState('user-teen-1');
  const [decisions, setDecisions] = useState<TeenHandoverDecisionMap>(() => {
    const initial: TeenHandoverDecisionMap = {};
    for (const conn of connections) {
      initial[conn.id] = 'keep';
    }
    return initial;
  });

  const handleToggleViewerSection = (section: ViewerSectionKey) => {
    setAllowedSections((prev) =>
      prev.includes(section)
        ? prev.filter((s) => s !== section)
        : [...prev, section]
    );
  };

  const handleSetDecision = (
    connId: string,
    decision: TeenHandoverDecision
  ) => {
    setDecisions((prev) => ({
      ...prev,
      [connId]: decision,
    }));
  };

  return (
    <div
      data-testid="companion-and-handover-panel"
      className={cn('space-y-8', className)}
    >
      {/* Section 1: iOS Companion Pairing (AU-62) */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-[var(--cf-fg)]">
              iOS Companion Pairing (HealthKit &amp; Clinical Records Bridge)
            </h3>
            <p className="text-xs text-[var(--cf-fg-muted)]">
              Pair your iPhone over LAN/Tailscale using a pinned TLS certificate SHA-256 fingerprint and one-time pairing token.
            </p>
          </div>
          <span
            data-testid="companion-mode-s-guard-badge"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60"
          >
            <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
            Mode S / TLS Cert Fingerprint Pinning Active
          </span>
        </div>

        {/* Paired Devices List */}
        {companionDevices.length > 0 && (
          <div data-testid="companion-devices-list" className="space-y-3">
            {companionDevices.map((device) => (
              <Card
                key={device.id}
                data-testid={`companion-device-card-${device.id}`}
                className="p-4 flex flex-wrap items-center justify-between gap-4 border border-[var(--cf-border)] shadow-sm"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Smartphone className="w-4 h-4 text-emerald-600 shrink-0" />
                    <h4 className="text-sm font-bold text-[var(--cf-fg)]">
                      {device.device_name}
                    </h4>
                    <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60">
                      {device.status}
                    </span>
                  </div>

                  <p
                    data-testid={`companion-cert-fingerprint-${device.id}`}
                    className="text-[11px] font-mono text-[var(--cf-fg-muted)]"
                  >
                    TLS SHA-256: {device.cert_fingerprint_sha256}
                  </p>

                  <div className="flex flex-wrap gap-1 pt-1">
                    {device.allowed_categories.map((cat) => (
                      <span
                        key={cat}
                        className="px-2 py-0.5 rounded bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-[10px] font-medium text-[var(--cf-fg)]"
                      >
                        {cat}
                      </span>
                    ))}
                  </div>
                </div>

                {device.status === 'active' && (
                  <Button
                    size="sm"
                    variant="danger"
                    data-testid={`companion-revoke-btn-${device.id}`}
                    leftIcon={<Trash2 className="w-3.5 h-3.5" />}
                    onClick={() => onRevokeCompanionDevice?.(device.id)}
                  >
                    Revoke Device
                  </Button>
                )}
              </Card>
            ))}
          </div>
        )}

        {/* Generate Pairing QR Card */}
        <Card className="p-4 space-y-3 border border-[var(--cf-border)] shadow-sm">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex-1 min-w-[220px]">
              <label
                htmlFor="companion-device-name-input"
                className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
              >
                iOS Device Label
              </label>
              <input
                id="companion-device-name-input"
                type="text"
                data-testid="companion-device-name-input"
                value={deviceName}
                onChange={(e) => setDeviceName(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>

            <Button
              type="button"
              size="sm"
              variant="primary"
              data-testid="companion-generate-qr-btn"
              leftIcon={<QrCode className="w-3.5 h-3.5" />}
              onClick={() =>
                onGeneratePairingQr?.(deviceName.trim(), selectedCategories)
              }
            >
              Generate Pairing QR
            </Button>
          </div>

          {pairingQr && (
            <div
              data-testid="companion-qr-display"
              className="p-3 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-1.5 text-xs"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-[var(--cf-fg)]">
                  One-Time Pairing Code:{' '}
                  <code
                    data-testid="companion-qr-code"
                    className="font-mono text-emerald-700 dark:text-emerald-300"
                  >
                    {pairingQr.pairing_code}
                  </code>
                </span>
                <span className="text-[11px] font-mono text-[var(--cf-fg-muted)]">
                  Endpoint: {pairingQr.host}:{pairingQr.port}
                </span>
              </div>
              <p
                data-testid="companion-qr-fingerprint"
                className="text-[11px] font-mono text-[var(--cf-fg-muted)]"
              >
                Pinned TLS Cert SHA-256: {pairingQr.cert_fingerprint_sha256}
              </p>
            </div>
          )}
        </Card>
      </section>

      {/* Section 2: Viewer Section Permissions (AU-63) */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-bold text-[var(--cf-fg)]">
            Granular Viewer Section Permissions ({viewerUserId})
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Restrict which profile sections a viewer (e.g. grandparent or school caregiver) can inspect; connections and clinical notes are hidden by default.
          </p>
        </div>

        <Card className="p-4 space-y-4 border border-[var(--cf-border)] shadow-sm">
          <div
            data-testid="viewer-sections-grid"
            className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
          >
            {ALL_VIEWER_SECTIONS.map((section) => {
              const checked = allowedSections.includes(section);
              return (
                <label
                  key={section}
                  className="flex items-center gap-2 p-2 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface-2)] text-xs cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    data-testid={`viewer-section-checkbox-${section}`}
                    onChange={() => handleToggleViewerSection(section)}
                    className="rounded border-[var(--cf-border)] text-emerald-600"
                  />
                  <span className="font-mono text-[11px] text-[var(--cf-fg)]">
                    {section}
                  </span>
                </label>
              );
            })}
          </div>

          <div className="flex justify-end">
            <Button
              type="button"
              size="sm"
              variant="primary"
              data-testid="viewer-sections-save-btn"
              leftIcon={<Lock className="w-3.5 h-3.5" />}
              onClick={() =>
                onSaveViewerSections?.(viewerUserId, allowedSections)
              }
            >
              Save Viewer Permissions
            </Button>
          </div>
        </Card>
      </section>

      {/* Section 3: Teen Connection Handover & DEK Rotation Wizard (AU-63) */}
      <section className="space-y-3">
        <div>
          <h3 className="text-sm font-bold text-[var(--cf-fg)]">
            Teen Connection Handover &amp; Vault DEK Re-Key Wizard
          </h3>
          <p className="text-xs text-[var(--cf-fg-muted)]">
            Transfer profile stewardship to a teen user: select which connections to keep (re-encrypted under the new Teen DEK) or revoke via the 4-step cascade.
          </p>
        </div>

        <Card className="p-4 space-y-4 border border-[var(--cf-border)] shadow-sm">
          <div className="max-w-sm">
            <label
              htmlFor="teen-steward-user-input"
              className="block text-[11px] font-medium text-[var(--cf-fg-muted)] mb-1"
            >
              New Teen Steward User ID
            </label>
            <input
              id="teen-steward-user-input"
              type="text"
              data-testid="teen-steward-user-input"
              value={newStewardUserId}
              onChange={(e) => setNewStewardUserId(e.target.value)}
              className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)] focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div
            data-testid="teen-handover-connections-list"
            className="space-y-2.5"
          >
            {connections.map((conn) => {
              const currentDecision = decisions[conn.id] ?? 'keep';
              return (
                <div
                  key={conn.id}
                  data-testid={`teen-handover-row-${conn.id}`}
                  className="p-3 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface-2)] flex flex-wrap items-center justify-between gap-3"
                >
                  <div>
                    <p className="text-xs font-bold text-[var(--cf-fg)]">
                      {conn.label}
                    </p>
                    <p className="text-[11px] font-mono text-[var(--cf-fg-muted)]">
                      {conn.id} • {conn.connector_id}
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant={
                        currentDecision === 'keep' ? 'primary' : 'outline'
                      }
                      data-testid={`teen-handover-keep-${conn.id}`}
                      onClick={() => handleSetDecision(conn.id, 'keep')}
                    >
                      Keep (Re-encrypt to Teen DEK)
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant={
                        currentDecision === 'revoke' ? 'danger' : 'outline'
                      }
                      data-testid={`teen-handover-revoke-${conn.id}`}
                      onClick={() => handleSetDecision(conn.id, 'revoke')}
                    >
                      Revoke (4-Step Cascade)
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>

          {handoverResult && (
            <div
              data-testid="teen-handover-dek-result"
              className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800/60 text-xs text-emerald-900 dark:text-emerald-200 flex items-center gap-2"
            >
              <KeyRound className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>
                Handover complete for{' '}
                <strong>{handoverResult.new_steward_user_id}</strong> — Rotated
                to Vault DEK v{handoverResult.new_dek_version} (Kept:{' '}
                {handoverResult.kept_connections.length}, Revoked:{' '}
                {handoverResult.revoked_connections.length})
              </span>
            </div>
          )}

          <div className="flex justify-end">
            <Button
              type="button"
              size="sm"
              variant="primary"
              data-testid="teen-handover-execute-btn"
              leftIcon={<UserCheck className="w-3.5 h-3.5" />}
              onClick={() =>
                onExecuteTeenHandover?.({
                  new_steward_user_id: newStewardUserId.trim(),
                  connection_decisions: decisions,
                })
              }
            >
              Execute Teen Handover
            </Button>
          </div>
        </Card>
      </section>
    </div>
  );
}
