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
  AuditChainVerificationResponse,
  OsServiceDescriptorItem,
  SmartHealthCardVerificationResult,
  SmartSchedulingSlotItem,
  V2ConnectorSummary,
  ZocdocBookingPreview,
} from '@/types/coordinatedCare';

export interface VerifySmartHealthCardPayload {
  filename: string;
  content: string;
  source_name?: string;
}

export interface DiscoverSmartSchedulingSlotsPayload {
  specialty?: string;
  manifest_payload?: Record<string, unknown>;
}

export interface PreviewZocdocBookingPayload {
  provider_id: string;
  provider_name: string;
  specialty: string;
  slot_id: string;
  start_time: string;
  insurance_carrier?: string;
}

export async function verifySmartHealthCard(
  profileId: string,
  payload: VerifySmartHealthCardPayload
): Promise<SmartHealthCardVerificationResult> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/imports/stage`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        format: 'smart_health_card',
        ...payload,
      }),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to verify SMART Health Card (${res.status})`
    );
  }
  return res.json();
}

export async function discoverSmartSchedulingSlots(
  profileId: string,
  payload: DiscoverSmartSchedulingSlotsPayload = {}
): Promise<{ slots: SmartSchedulingSlotItem[] }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/scheduling/smart-slots`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to discover SMART scheduling slots (${res.status})`
    );
  }
  return res.json();
}

export async function previewZocdocBooking(
  profileId: string,
  payload: PreviewZocdocBookingPayload
): Promise<{ booking_preview: ZocdocBookingPreview }> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/scheduling/zocdoc-preview`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to preview Zocdoc booking (${res.status})`
    );
  }
  return res.json();
}

export async function verifyProfileAuditChain(
  profileId: string
): Promise<AuditChainVerificationResponse> {
  const res = await fetch(
    `/api/v1/profiles/${encodeURIComponent(profileId)}/audit/verify`,
    { credentials: 'include' }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to verify profile audit hash chain (${res.status})`
    );
  }
  return res.json();
}

export async function fetchOsServiceDescriptors(): Promise<{
  descriptors: OsServiceDescriptorItem[];
}> {
  const res = await fetch('/api/v1/system/service-descriptors', {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch OS service descriptors (${res.status})`
    );
  }
  return res.json();
}

export async function fetchV2ConnectorCatalog(): Promise<{
  connectors: V2ConnectorSummary[];
}> {
  const res = await fetch('/api/v1/connectors/v2-catalog', {
    credentials: 'include',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      err.detail || `Failed to fetch v2 connector catalog (${res.status})`
    );
  }
  return res.json();
}
