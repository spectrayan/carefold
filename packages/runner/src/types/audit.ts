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

export type AuditEventType = 'run' | 'tool' | 'refuse' | 'error';

export interface AuditEvent {
  ts?: string;                 // ISO 8601 UTC timestamp (auto-generated if omitted)
  agent_id: string;
  skill_id?: string;
  skill_version?: string;
  event: AuditEventType;
  tool?: string;
  allowed?: boolean;
  reason?: string;
  duration_ms?: number;
  prompt?: string;            // Redacted unless audit.store_bodies: true
  completion?: string;        // Redacted unless audit.store_bodies: true
}
