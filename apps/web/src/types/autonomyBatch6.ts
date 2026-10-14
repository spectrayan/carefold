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

export type McpToolPinStatus = 'pinned' | 'drift_blocked';

export interface McpToolPinItem {
  id: string;
  connection_id: string;
  tool_name: string;
  risk_tier: 'A0' | 'A1' | 'A2' | string;
  schema_hash: string;
  status: McpToolPinStatus;
  verified_at: string;
  output_taint?: 'untrusted' | string;
  description?: string;
}

export type StandingRoutineStatus = 'active' | 'paused' | 'revoked' | 'expired';

export interface StandingRoutineItem {
  id: string;
  profile_id: string;
  connection_id: string;
  name: string;
  tool_name: string;
  rrule: string;
  timezone: string;
  status: StandingRoutineStatus;
  expires_at: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
}

export interface CreateStandingRoutinePayload {
  connection_id: string;
  name: string;
  tool_name: string;
  rrule: string;
  timezone: string;
  expires_in_days: number;
}

export interface EmailDraftItem {
  id: string;
  profile_id: string;
  recipient: string;
  subject: string;
  body: string;
  category: string;
  status: 'draft' | 'exported' | 'archived' | string;
  mailto_uri: string;
  created_at: string;
}

export interface CreateEmailDraftPayload {
  recipient: string;
  subject: string;
  body: string;
  category?: string;
}

export interface GmailStagedCandidate {
  index: number;
  record_type: 'appointment' | 'todo' | string;
  title: string;
  summary: string;
  source_display: string;
  trust: 'untrusted';
  confirmed: boolean;
}

export interface SchoolIcsFeedItem {
  id: string;
  profile_id: string;
  label: string;
  feed_url: string;
  status: 'active' | 'degraded' | 'revoked' | string;
  events_synced: number;
  last_synced_at?: string | null;
}

export interface CreateSchoolIcsFeedPayload {
  label: string;
  feed_url: string;
}

export interface CompanionDeviceItem {
  id: string;
  profile_id: string;
  device_name: string;
  platform: 'ios' | string;
  cert_fingerprint_sha256: string;
  allowed_categories: string[];
  status: 'active' | 'revoked' | string;
  last_seen_at?: string | null;
}

export interface CompanionPairingQrPayload {
  device_id: string;
  host: string;
  port: number;
  pairing_code: string;
  cert_fingerprint_sha256: string;
  allowed_categories: string[];
  expires_at: string;
}

export type ViewerSectionKey =
  | 'vitals'
  | 'preventive'
  | 'appointments'
  | 'reminders'
  | 'connections'
  | 'school_forms'
  | 'notes'
  | 'documents';

export interface ViewerSectionPermissions {
  profile_id: string;
  viewer_user_id: string;
  allowed_sections: ViewerSectionKey[];
}

export type TeenHandoverDecision = 'keep' | 'revoke';

export type TeenHandoverDecisionMap = Record<string, TeenHandoverDecision>;

export interface TeenHandoverPayload {
  new_steward_user_id: string;
  connection_decisions: TeenHandoverDecisionMap;
}

export interface TeenHandoverResponse {
  profile_id: string;
  new_steward_user_id: string;
  new_dek_version: number;
  kept_connections: string[];
  revoked_connections: string[];
}
