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
  ShieldCheck,
  FileText,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { InsuranceBenefitsCard } from '@/health-ui/InsuranceBenefitsCard';
import type { InsuranceBenefitsDossierData } from '@/lib/types';

export interface CoverageClientProps {
  profileId: string;
}

interface CoveragePlanRecord {
  id: string;
  plan_name: string;
  payer_name: string;
  policy_number?: string;
  group_number?: string;
  coverage_type?: string;
  is_active: boolean;
  start_date?: string;
  end_date?: string;
  deductible_individual_cents?: number;
  deductible_family_cents?: number;
  deductible_met_cents?: number;
  oop_max_individual_cents?: number;
  oop_max_family_cents?: number;
  oop_met_cents?: number;
  copay_primary_cents?: number;
  copay_specialist_cents?: number;
  copay_urgent_cents?: number;
  copay_er_cents?: number;
  coinsurance_rate?: number;
  raw_details?: Record<string, unknown>;
}

interface ClaimRecord {
  id: string;
  claim_number: string;
  service_date?: string;
  billed_amount_cents: number;
  allowed_amount_cents?: number;
  paid_amount_cents?: number;
  patient_responsibility_cents?: number;
  status: string;
  provider_name?: string;
  denial_reason?: string;
}

interface AppealRecord {
  id: string;
  claim_id?: string;
  prior_auth_id?: string;
  appeal_level: number;
  status: string;
  submitted_date?: string;
  deadline_date?: string;
  reason_summary?: string;
}

interface PriorAuthRecord {
  id: string;
  auth_number: string;
  service_code: string;
  status: string;
  requested_date?: string;
  valid_until?: string;
  provider_name?: string;
  urgency?: string;
}

export function CoverageClient({ profileId }: CoverageClientProps) {
  const [plans, setPlans] = useState<CoveragePlanRecord[]>([]);
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [appeals, setAppeals] = useState<AppealRecord[]>([]);
  const [priorAuths, setPriorAuths] = useState<PriorAuthRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<'benefits' | 'claims' | 'prior-auth'>('benefits');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [plansRes, claimsRes, appealsRes, paRes] = await Promise.all([
        fetch(`/api/v1/profiles/${profileId}/coverage`).catch(() => null),
        fetch(`/api/v1/profiles/${profileId}/claims`).catch(() => null),
        fetch(`/api/v1/profiles/${profileId}/appeals`).catch(() => null),
        fetch(`/api/v1/profiles/${profileId}/prior-authorizations`).catch(() => null),
      ]);

      if (plansRes && plansRes.ok) {
        const data = await plansRes.json();
        setPlans(Array.isArray(data) ? data : []);
      }
      if (claimsRes && claimsRes.ok) {
        const data = await claimsRes.json();
        setClaims(Array.isArray(data) ? data : []);
      }
      if (appealsRes && appealsRes.ok) {
        const data = await appealsRes.json();
        setAppeals(Array.isArray(data) ? data : []);
      }
      if (paRes && paRes.ok) {
        const data = await paRes.json();
        setPriorAuths(Array.isArray(data) ? data : []);
      }
    } catch {
      // Ignore network errors in demo/offline
    } finally {
      setLoading(false);
    }
  }, [profileId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Convert active plan to dossier data for InsuranceBenefitsCard
  const activePlan = plans.find((p) => p.is_active) ?? plans[0];
  const dossierData: InsuranceBenefitsDossierData = activePlan
    ? {
        deductible: `$${((activePlan.deductible_individual_cents ?? 150000) / 100).toLocaleString()} Individual / $${((activePlan.deductible_family_cents ?? 300000) / 100).toLocaleString()} Family`,
        out_of_pocket_maximum: `$${((activePlan.oop_max_individual_cents ?? 450000) / 100).toLocaleString()} Individual / $${((activePlan.oop_max_family_cents ?? 900000) / 100).toLocaleString()} Family`,
        coinsurance: activePlan.coinsurance_rate
          ? `${Math.round(activePlan.coinsurance_rate * 100)}% after deductible`
          : '20% after deductible',
        copays: {
          primary_care_visit: `$${((activePlan.copay_primary_cents ?? 2500) / 100).toFixed(0)}`,
          specialist_visit: `$${((activePlan.copay_specialist_cents ?? 5000) / 100).toFixed(0)}`,
          urgent_care: `$${((activePlan.copay_urgent_cents ?? 4000) / 100).toFixed(0)}`,
          emergency_room: `$${((activePlan.copay_er_cents ?? 25000) / 100).toFixed(0)}`,
          generic_prescription: '$10',
          preferred_brand_prescription: '$35',
        },
        in_out_network_rules:
          'In-network preventive care is covered at 100% without deductible. Out-of-network services require separate cost sharing.',
        prior_authorization_flags: [
          'Advanced Diagnostic Imaging (MRI, CT, PET)',
          'Specialty Injectable Biologics',
          'Inpatient Hospital Admissions',
          'Outpatient Surgeries & Endoscopies',
        ],
      }
    : {
        deductible: '$1,500 Individual / $3,000 Family',
        out_of_pocket_maximum: '$4,500 Individual / $9,000 Family',
        coinsurance: '20% after deductible',
        copays: {
          primary_care_visit: '$25',
          specialist_visit: '$50',
          urgent_care: '$40',
          emergency_room: '$250',
          generic_prescription: '$10',
          preferred_brand_prescription: '$35',
        },
        in_out_network_rules:
          'In-network preventive care is covered at 100% without deductible. Out-of-network services require a separate deductible with coinsurance.',
        prior_authorization_flags: [
          'Advanced Diagnostic Imaging (MRI, CT, PET)',
          'Specialty Injectable Biologics',
          'Inpatient Hospital Admissions (except emergency)',
          'Outpatient Surgeries & Endoscopies',
        ],
      };

  const formatCents = (cents?: number) => {
    if (cents === undefined || cents === null) return '—';
    return `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl space-y-6">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--cf-border)] pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--cf-fg)]">
            Health Insurance & Benefits Trackers
          </h1>
          <p className="text-sm text-[var(--cf-fg-muted)]">
            Coverage plans, claims tracking, appeals management, and prior-authorization records.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchData}
            disabled={loading}
            aria-label="Refresh insurance data"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 me-1.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="w-4 h-4 me-1.5" aria-hidden="true" />
            )}
            Refresh
          </Button>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex border-b border-[var(--cf-border)] space-x-4">
        <button
          type="button"
          onClick={() => setActiveTab('benefits')}
          className={`pb-3 text-sm font-semibold transition-colors border-b-2 ${
            activeTab === 'benefits'
              ? 'border-[var(--cf-primary)] text-[var(--cf-primary)]'
              : 'border-transparent text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
          }`}
        >
          Benefits & Cost Sharing
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('claims')}
          className={`pb-3 text-sm font-semibold transition-colors border-b-2 ${
            activeTab === 'claims'
              ? 'border-[var(--cf-primary)] text-[var(--cf-primary)]'
              : 'border-transparent text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
          }`}
        >
          Claims & Appeals ({claims.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('prior-auth')}
          className={`pb-3 text-sm font-semibold transition-colors border-b-2 ${
            activeTab === 'prior-auth'
              ? 'border-[var(--cf-primary)] text-[var(--cf-primary)]'
              : 'border-transparent text-[var(--cf-fg-muted)] hover:text-[var(--cf-fg)]'
          }`}
        >
          Prior Authorizations ({priorAuths.length})
        </button>
      </div>

      {/* Tab Panels */}
      {activeTab === 'benefits' && (
        <section aria-label="Insurance Benefits Dossier" className="space-y-6">
          <InsuranceBenefitsCard
            data={dossierData}
            agentTitle="Benefits Coordinator"
            isGrounded={true}
          />
        </section>
      )}

      {activeTab === 'claims' && (
        <section aria-label="Claims and Appeals Tracker" className="space-y-4">
          {claims.length === 0 ? (
            <EmptyState
              icon={<FileText className="w-8 h-8 text-[var(--cf-fg-muted)]" />}
              title="No Claims Recorded"
              description="No insurance claims have been submitted or tracked for this profile yet."
            />
          ) : (
            <div className="rounded-[var(--cf-radius-lg)] border border-[var(--cf-border)] bg-[var(--cf-surface)] overflow-hidden shadow-sm">
              <table className="w-full text-start text-sm" data-testid="claims-table">
                <thead className="border-b border-[var(--cf-border)] bg-[var(--cf-surface-muted)] text-[var(--cf-fg-muted)]">
                  <tr>
                    <th className="p-3 text-start font-medium">Claim #</th>
                    <th className="p-3 text-start font-medium">Provider</th>
                    <th className="p-3 text-start font-medium">Service Date</th>
                    <th className="p-3 text-start font-medium">Billed</th>
                    <th className="p-3 text-start font-medium">Patient Resp.</th>
                    <th className="p-3 text-start font-medium">Status</th>
                    <th className="p-3 text-start font-medium">Notes / Denial</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--cf-border)]">
                  {claims.map((claim) => (
                    <tr key={claim.id} className="hover:bg-[var(--cf-surface-hover)]">
                      <td className="p-3 font-semibold text-[var(--cf-fg)]">{claim.claim_number}</td>
                      <td className="p-3 text-[var(--cf-fg)]">{claim.provider_name || '—'}</td>
                      <td className="p-3 text-[var(--cf-fg-muted)]">{claim.service_date || '—'}</td>
                      <td className="p-3 text-[var(--cf-fg)]">{formatCents(claim.billed_amount_cents)}</td>
                      <td className="p-3 font-medium text-[var(--cf-fg)]">
                        {formatCents(claim.patient_responsibility_cents)}
                      </td>
                      <td className="p-3">
                        <Badge
                          variant={
                            claim.status === 'approved' || claim.status === 'paid'
                              ? 'success'
                              : claim.status === 'denied'
                              ? 'danger'
                              : 'warning'
                          }
                          size="sm"
                        >
                          {claim.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-xs text-[var(--cf-fg-muted)]">
                        {claim.denial_reason || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Appeals Section */}
          {appeals.length > 0 && (
            <div className="mt-8 space-y-3">
              <h2 className="text-lg font-bold text-[var(--cf-fg)]">Active Appeals</h2>
              <div className="space-y-2">
                {appeals.map((appeal) => (
                  <div
                    key={appeal.id}
                    className="flex items-center justify-between p-3 rounded-lg border border-[var(--cf-border)] bg-[var(--cf-surface)]"
                  >
                    <div>
                      <p className="font-semibold text-sm text-[var(--cf-fg)]">
                        Level {appeal.appeal_level} Appeal — {appeal.reason_summary || 'General Appeal'}
                      </p>
                      <p className="text-xs text-[var(--cf-fg-muted)]">
                        Submitted: {appeal.submitted_date || 'Pending'} | Deadline: {appeal.deadline_date || '—'}
                      </p>
                    </div>
                    <Badge variant={appeal.status === 'submitted' ? 'info' : 'warning'} size="sm">
                      {appeal.status}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {activeTab === 'prior-auth' && (
        <section aria-label="Prior Authorizations Tracker" className="space-y-4">
          {priorAuths.length === 0 ? (
            <EmptyState
              icon={<ShieldCheck className="w-8 h-8 text-[var(--cf-fg-muted)]" />}
              title="No Prior Authorizations"
              description="No prior authorization requests recorded for this profile."
            />
          ) : (
            <div className="rounded-[var(--cf-radius-lg)] border border-[var(--cf-border)] bg-[var(--cf-surface)] overflow-hidden shadow-sm">
              <table className="w-full text-start text-sm" data-testid="prior-auth-table">
                <thead className="border-b border-[var(--cf-border)] bg-[var(--cf-surface-muted)] text-[var(--cf-fg-muted)]">
                  <tr>
                    <th className="p-3 text-start font-medium">Auth #</th>
                    <th className="p-3 text-start font-medium">Service Code</th>
                    <th className="p-3 text-start font-medium">Provider</th>
                    <th className="p-3 text-start font-medium">Urgency</th>
                    <th className="p-3 text-start font-medium">Status</th>
                    <th className="p-3 text-start font-medium">Valid Until</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--cf-border)]">
                  {priorAuths.map((pa) => (
                    <tr key={pa.id} className="hover:bg-[var(--cf-surface-hover)]">
                      <td className="p-3 font-semibold text-[var(--cf-fg)]">{pa.auth_number}</td>
                      <td className="p-3 text-[var(--cf-fg)]">{pa.service_code}</td>
                      <td className="p-3 text-[var(--cf-fg)]">{pa.provider_name || '—'}</td>
                      <td className="p-3">
                        <Badge
                          variant={pa.urgency === 'urgent' ? 'danger' : 'neutral'}
                          size="sm"
                        >
                          {pa.urgency || 'standard'}
                        </Badge>
                      </td>
                      <td className="p-3">
                        <Badge
                          variant={
                            pa.status === 'approved' || pa.status === 'emergency_bypass'
                              ? 'success'
                              : pa.status === 'denied'
                              ? 'danger'
                              : 'warning'
                          }
                          size="sm"
                        >
                          {pa.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-xs text-[var(--cf-fg-muted)]">
                        {pa.valid_until || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
