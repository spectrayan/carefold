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

import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Globe,
  Lock,
  KeyRound,
  CheckCircle2,
  X,
} from 'lucide-react';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { cn } from '@/lib/utils';
import type {
  ConnectorManifestSummary,
  CreateConnectionPayload,
} from '@/types/connections';

export interface ConnectorConsentModalProps {
  connector: ConnectorManifestSummary;
  isOpen?: boolean;
  isSubmitting?: boolean;
  defaultTermsVersion?: string;
  onConfirm: (payload: CreateConnectionPayload) => void | Promise<void>;
  onCancel: () => void;
}

const DEFAULT_TERMS_VERSION = '2026-10-01';

export function ConnectorConsentModal({
  connector,
  isOpen = true,
  isSubmitting = false,
  defaultTermsVersion = DEFAULT_TERMS_VERSION,
  onConfirm,
  onCancel,
}: ConnectorConsentModalProps) {
  const [selectedCategories, setSelectedCategories] = useState<string[]>(
    () => [...connector.categories]
  );
  const [label, setLabel] = useState<string>(connector.name);
  const [purpose, setPurpose] = useState<string>(
    `Synchronise ${connector.name} records into local Carefold profile`
  );
  const [clientId, setClientId] = useState<string>('');
  const [clientSecret, setClientSecret] = useState<string>('');
  const [attested, setAttested] = useState<boolean>(true);

  useEffect(() => {
    setSelectedCategories([...connector.categories]);
    setLabel(connector.name);
    setPurpose(
      `Synchronise ${connector.name} records into local Carefold profile`
    );
    setClientId('');
    setClientSecret('');
    setAttested(true);
  }, [connector.id, connector.name, connector.categories]);

  if (!isOpen) {
    return null;
  }

  const isTrustedDevice = connector.trust_level === 'trusted_device';

  const handleToggleCategory = (cat: string) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedCategories.length === 0 || !attested) return;

    const payload: CreateConnectionPayload = {
      connector_id: connector.id,
      label: label.trim() || connector.name,
      categories: selectedCategories,
      scopes: connector.scopes,
      purpose: purpose.trim(),
      terms_version: defaultTermsVersion,
      ...(clientId.trim() ? { client_id: clientId.trim() } : {}),
      ...(clientSecret.trim() ? { client_secret: clientSecret.trim() } : {}),
    };

    // Clear ephemeral secret state immediately after constructing request payload
    setClientSecret('');
    await onConfirm(payload);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="connector-consent-title"
      data-testid="connector-consent-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto"
    >
      <Card className="w-full max-w-xl p-6 space-y-5 shadow-xl border border-[var(--cf-border)] bg-[var(--cf-surface)]">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 pb-3 border-b border-[var(--cf-border)]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-600/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center shrink-0">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2
                id="connector-consent-title"
                className="text-base font-bold text-[var(--cf-fg)]"
              >
                Granular Data &amp; Egress Consent — {connector.name}
              </h2>
              <p className="text-xs text-[var(--cf-fg-muted)]">
                Manifest v{connector.version} • {connector.auth_type.toUpperCase()}
                {connector.pkce ? ' + PKCE (S256)' : ''}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Close consent modal"
            data-testid="consent-modal-close-btn"
            onClick={onCancel}
            className="p-1.5 rounded-lg text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)] hover:bg-[var(--cf-surface-2)]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Trust Classification Badge */}
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-[var(--cf-fg)]">
              Ingestion Trust &amp; Security Classification
            </span>
            <div
              data-testid="consent-trust-badge"
              className={cn(
                'inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border',
                isTrustedDevice
                  ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-800 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60'
                  : 'bg-amber-50 dark:bg-amber-950/30 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800/60'
              )}
            >
              {isTrustedDevice ? (
                <>
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                  <span>Trusted Structured Device Data</span>
                </>
              ) : (
                <>
                  <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0" />
                  <span>Untrusted External Clinical Narrative — Taint Enabled</span>
                </>
              )}
            </div>
          </div>

          {/* Data Categories Checkboxes */}
          <div className="space-y-2">
            <span className="block text-xs font-semibold text-[var(--cf-fg)]">
              Authorized Data Categories
            </span>
            <div
              data-testid="consent-categories-list"
              className="grid grid-cols-1 sm:grid-cols-2 gap-2"
            >
              {connector.categories.map((category) => {
                const checked = selectedCategories.includes(category);
                return (
                  <label
                    key={category}
                    data-testid={`consent-category-label-${category}`}
                    className={cn(
                      'flex items-center gap-2.5 p-2.5 rounded-lg border text-xs cursor-pointer transition-colors',
                      checked
                        ? 'border-emerald-600 bg-emerald-50/50 dark:bg-emerald-950/20 font-medium text-[var(--cf-fg)]'
                        : 'border-[var(--cf-border)] bg-[var(--cf-surface)] text-[var(--cf-fg-muted)]'
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      data-testid={`consent-category-checkbox-${category}`}
                      onChange={() => handleToggleCategory(category)}
                      className="rounded border-[var(--cf-border)] text-emerald-600 focus:ring-emerald-500"
                    />
                    <span className="capitalize">
                      {category.replace(/_/g, ' ')}
                    </span>
                  </label>
                );
              })}
            </div>
          </div>

          {/* Outbound Destination Hosts */}
          <div className="space-y-1.5">
            <span className="block text-xs font-semibold text-[var(--cf-fg)]">
              Allowlisted Outbound Destination Hosts
            </span>
            <div
              data-testid="consent-allowed-hosts"
              className="flex flex-wrap gap-1.5"
            >
              {connector.allowed_hosts.map((host) => (
                <span
                  key={host}
                  data-testid={`consent-host-badge-${host}`}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[var(--cf-surface-2)] border border-[var(--cf-border)] text-xs font-mono text-[var(--cf-fg)]"
                >
                  <Globe className="w-3 h-3 text-emerald-600 shrink-0" />
                  {host}
                </span>
              ))}
            </div>
          </div>

          {/* Connection Label & Purpose */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="consent-connection-label"
                className="block text-xs font-semibold text-[var(--cf-fg)] mb-1"
              >
                Connection Label
              </label>
              <input
                id="consent-connection-label"
                data-testid="consent-label-input"
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)]"
              />
            </div>
            <div>
              <label
                htmlFor="consent-purpose-input"
                className="block text-xs font-semibold text-[var(--cf-fg)] mb-1"
              >
                Declared Purpose
              </label>
              <input
                id="consent-purpose-input"
                data-testid="consent-purpose-input"
                type="text"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className="w-full px-3 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs text-[var(--cf-fg)]"
              />
            </div>
          </div>

          {/* Optional BYO OAuth Client ID & Secret */}
          <div className="p-3.5 rounded-xl bg-[var(--cf-surface-2)] border border-[var(--cf-border)] space-y-3">
            <div className="flex items-center gap-2 text-xs font-semibold text-[var(--cf-fg)]">
              <KeyRound className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>Bring-Your-Own (BYO) OAuth Credentials (Optional)</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="consent-byo-client-id"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  OAuth Client ID
                </label>
                <input
                  id="consent-byo-client-id"
                  data-testid="consent-byo-client-id"
                  type="text"
                  autoComplete="off"
                  value={clientId}
                  onChange={(e) => setClientId(e.target.value)}
                  placeholder="Optional custom client_id"
                  className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)]"
                />
              </div>
              <div>
                <label
                  htmlFor="consent-byo-client-secret"
                  className="block text-xs font-medium text-[var(--cf-fg-muted)] mb-1"
                >
                  OAuth Client Secret
                </label>
                <input
                  id="consent-byo-client-secret"
                  data-testid="consent-byo-client-secret"
                  type="password"
                  autoComplete="new-password"
                  value={clientSecret}
                  onChange={(e) => setClientSecret(e.target.value)}
                  placeholder="Optional custom client_secret"
                  className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs font-mono text-[var(--cf-fg)]"
                />
              </div>
            </div>
            <p
              data-testid="consent-vault-security-notice"
              className="flex items-center gap-1.5 text-xs text-[var(--cf-fg-muted)]"
            >
              <Lock className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              <span>
                Encrypted in your local Carefold Vault via AES-256-GCM; never stored in browser storage
              </span>
            </p>
          </div>

          {/* Terms Version Attestation */}
          <label
            data-testid="consent-terms-attestation"
            className="flex items-start gap-2.5 p-3 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)] text-xs cursor-pointer"
          >
            <input
              type="checkbox"
              checked={attested}
              data-testid="consent-attest-checkbox"
              onChange={(e) => setAttested(e.target.checked)}
              className="mt-0.5 rounded border-[var(--cf-border)] text-emerald-600"
            />
            <span className="text-[var(--cf-fg-muted)] leading-relaxed">
              I authorize Carefold to connect to{' '}
              <strong className="text-[var(--cf-fg)]">{connector.name}</strong>{' '}
              under Consent Terms{' '}
              <span
                data-testid="consent-terms-version"
                className="font-mono font-semibold text-[var(--cf-fg)]"
              >
                v{defaultTermsVersion}
              </span>{' '}
              and verify that clinical data remains local-first on this device.
            </span>
          </label>

          {/* Actions */}
          <div className="flex items-center justify-end gap-2 pt-2 border-t border-[var(--cf-border)]">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              data-testid="consent-cancel-btn"
              onClick={onCancel}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={isSubmitting}
              disabled={
                isSubmitting || selectedCategories.length === 0 || !attested
              }
              data-testid="consent-confirm-btn"
            >
              Confirm Consent &amp; Connect
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
