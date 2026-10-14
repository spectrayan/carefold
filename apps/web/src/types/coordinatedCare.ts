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

/**
 * TypeScript interfaces for Carefold Autonomy Batch 7 ("Coordinated" v2):
 * - SMART Health Card (SHC) JWS ES256 verification (AU-77)
 * - SMART Scheduling Links & Zocdoc irreversible booking preview (AU-71, AU-72)
 * - Expanded v2 SMART EHRs, Payers & Wearables (AU-73, AU-74)
 * - Android Health Connect Companion support (AU-75)
 * - Gmail Send irreversible approval flow (AU-76)
 * - Tamper-Evident Audit Hash Chain verification (AU-78)
 * - OS Background Service descriptors (AU-81)
 */

export interface SmartHealthCardVerificationResult {
  batch_id: string;
  verification_status: 'verified' | 'unverified_issuer' | 'invalid_signature';
  issuer: string;
  records_count: number;
  summary: {
    immunisations: number;
    observations: number;
  };
  staged_records: Array<{
    resource_type: string;
    display: string;
    effective_at: string;
    source_display: string;
    trust: 'untrusted';
  }>;
}

export interface SmartSchedulingSlotItem {
  slot_id: string;
  provider_name: string;
  specialty: string;
  location: string;
  start_time: string;
  end_time: string;
  fits_calendar: boolean;
  booking_url?: string | null;
  source: 'smart_scheduling_links' | 'zocdoc';
}

export interface ZocdocBookingPreview {
  provider_id: string;
  provider_name: string;
  specialty: string;
  slot_id: string;
  start_time: string;
  insurance_carrier?: string | null;
  risk_tier: 'irreversible';
  requires_approval: true;
  payload_hash: string;
  status: 'approval_required' | 'booked';
}

export interface AuditChainVerificationResponse {
  profile_id: string;
  valid: boolean;
  checked_count: number;
  head_hash: string | null;
  broken_at_event_id: string | null;
  reason: string | null;
}

export interface OsServiceDescriptorItem {
  platform: 'macos_launchd' | 'linux_systemd' | 'windows_task_scheduler';
  filename: string;
  install_path: string;
  content: string;
  install_command: string;
}

export interface V2ConnectorSummary {
  id: string;
  name: string;
  category: 'ehr_smart' | 'payer' | 'wearable' | 'calendar' | 'booking';
  trust_level: 'trusted' | 'untrusted';
  risk_tier: 'read' | 'write_external' | 'irreversible';
  allowed_hosts: string[];
}
