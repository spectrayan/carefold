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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import {
  McpPinsAndRoutinesPanel,
  EmailDraftsAndSchoolFeedsPanel,
  CompanionAndHandoverPanel,
  ConnectionsHub,
} from '@/components/connections';
import {
  fetchMcpToolPins,
  reapproveMcpToolPin,
  fetchStandingRoutines,
  createStandingRoutine,
  pauseStandingRoutine,
  revokeStandingRoutine,
  fetchGmailStagedCandidates,
  confirmGmailStagedCandidate,
  fetchEmailDrafts,
  createEmailDraft,
  downloadEmailDraftEml,
  fetchSchoolIcsFeeds,
  createSchoolIcsFeed,
  syncSchoolIcsFeed,
  fetchCompanionDevices,
  generateCompanionPairingQr,
  revokeCompanionDevice,
  fetchViewerSectionPermissions,
  updateViewerSectionPermissions,
  executeTeenHandover,
} from '@/lib/autonomyBatch6Client';
import type {
  CompanionDeviceItem,
  CompanionPairingQrPayload,
  EmailDraftItem,
  GmailStagedCandidate,
  McpToolPinItem,
  SchoolIcsFeedItem,
  StandingRoutineItem,
  TeenHandoverResponse,
} from '@/types/autonomyBatch6';
import type {
  ConnectionItem,
  ConnectorManifestSummary,
} from '@/types/connections';

const SAMPLE_MCP_PINS: McpToolPinItem[] = [
  {
    id: 'pin-withings-1',
    connection_id: 'conn-withings-1',
    tool_name: 'withings.fetch_daily_vitals',
    risk_tier: 'A1',
    schema_hash: 'e3b0c44298fc1c149afbf4c8996fb924',
    status: 'pinned',
    verified_at: '2026-10-13T12:00:00Z',
    output_taint: 'untrusted',
    description: 'Read-only daily blood pressure and weight metrics.',
  },
  {
    id: 'pin-fhir-2',
    connection_id: 'conn-epic-1',
    tool_name: 'fhir.search_immunizations',
    risk_tier: 'A1',
    schema_hash: '9f86d081884c7d659a2feaa0c55ad015',
    status: 'drift_blocked',
    verified_at: '2026-10-13T12:05:00Z',
    output_taint: 'untrusted',
    description: 'SMART on FHIR immunization history lookup.',
  },
];

const SAMPLE_ROUTINES: StandingRoutineItem[] = [
  {
    id: 'rt-101',
    profile_id: 'prof-1',
    connection_id: 'conn-withings-1',
    name: 'Morning BP Check Digest',
    tool_name: 'withings.fetch_daily_vitals',
    rrule: 'FREQ=DAILY;BYHOUR=7;BYMINUTE=30',
    timezone: 'America/Chicago',
    status: 'active',
    expires_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
    last_run_at: '2026-10-13T07:30:00Z',
    next_run_at: '2026-10-14T07:30:00Z',
  },
];

const SAMPLE_GMAIL_CANDIDATES: GmailStagedCandidate[] = [
  {
    index: 0,
    record_type: 'appointment',
    title: 'Pediatric Dental Cleaning — Dr. Patel',
    summary: 'Appointment confirmation for Nov 4 at 3:30 PM.',
    source_display: 'From Gmail, Oct 13 (Pediatric Dental Clinic)',
    trust: 'untrusted',
    confirmed: false,
  },
  {
    index: 1,
    record_type: 'todo',
    title: 'Submit Vision Screening Form',
    summary: 'Google Classroom Guardian Digest reminder for Grade 4.',
    source_display: 'From Gmail, Oct 13 (Google Classroom Digest)',
    trust: 'untrusted',
    confirmed: true,
  },
];

const SAMPLE_EMAIL_DRAFTS: EmailDraftItem[] = [
  {
    id: 'draft-301',
    profile_id: 'prof-1',
    recipient: 'nurse@oakridge.edu',
    subject: 'Signed Asthma Action Plan Attached',
    body: 'Hello Nurse Miller, please find the updated asthma action plan.',
    category: 'school_nurse',
    status: 'draft',
    mailto_uri:
      'mailto:nurse@oakridge.edu?subject=Signed%20Asthma%20Action%20Plan%20Attached',
    created_at: '2026-10-13T11:00:00Z',
  },
];

const SAMPLE_SCHOOL_FEEDS: SchoolIcsFeedItem[] = [
  {
    id: 'feed-401',
    profile_id: 'prof-1',
    label: 'Oakridge Elementary Calendar',
    feed_url: 'https://calendar.oakridge.edu/events.ics',
    status: 'active',
    events_synced: 6,
    last_synced_at: '2026-10-13T11:30:00Z',
  },
];

const SAMPLE_COMPANION_DEVICES: CompanionDeviceItem[] = [
  {
    id: 'dev-501',
    profile_id: 'prof-1',
    device_name: 'Bharat iPhone 16 Pro',
    platform: 'ios',
    cert_fingerprint_sha256:
      'A1:B2:C3:D4:E5:F6:01:02:03:04:05:06:07:08:09:10:11:12:13:14:15:16:17:18:19:20:21:22:23:24:25:26',
    allowed_categories: ['vitals', 'clinical_records', 'reminders'],
    status: 'active',
    last_seen_at: '2026-10-13T12:10:00Z',
  },
];

const SAMPLE_PAIRING_QR: CompanionPairingQrPayload = {
  device_id: 'dev-502',
  host: '100.64.1.12',
  port: 8000,
  pairing_code: 'CF-884-921',
  cert_fingerprint_sha256:
    'A1:B2:C3:D4:E5:F6:01:02:03:04:05:06:07:08:09:10:11:12:13:14:15:16:17:18:19:20:21:22:23:24:25:26',
  allowed_categories: ['vitals', 'clinical_records', 'reminders'],
  expires_at: '2026-10-13T12:25:00Z',
};

const SAMPLE_CONNECTIONS: ConnectionItem[] = [
  {
    id: 'conn-withings-1',
    profile_id: 'prof-1',
    connector_id: 'withings',
    label: 'Withings BPM Connect',
    status: 'active',
    consecutive_failures: 0,
    consented_version: '1.0.0',
    created_at: '2026-10-01T08:00:00Z',
  },
  {
    id: 'conn-epic-1',
    profile_id: 'prof-1',
    connector_id: 'epic_mychart_fhir',
    label: 'Pediatric Epic MyChart',
    status: 'active',
    consecutive_failures: 0,
    consented_version: '1.0.0',
    created_at: '2026-10-02T08:00:00Z',
  },
];

const SAMPLE_CONNECTORS: ConnectorManifestSummary[] = [
  {
    id: 'withings',
    name: 'Withings Health Mate',
    version: '1.0.0',
    description: 'Blood pressure and weight monitors.',
    categories: ['vitals'],
    allowed_hosts: ['wbsapi.withings.net'],
    scopes: ['user.metrics'],
    auth_type: 'oauth2',
    pkce: true,
    client_source: 'byo_or_system',
    trust_level: 'trusted_device',
  },
];

describe('Connected Experience & Autonomy Batch 6 Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. McpPinsAndRoutinesPanel Component (AU-57 & AU-58)', () => {
    it('renders SHA-256 schema pins, taint indicators, drift-blocked re-approval, and A2 standing routines with <= 90 days expiry validation', async () => {
      const onReapprovePin = vi.fn();
      const onCreateRoutine = vi.fn();
      const onPauseRoutine = vi.fn();
      const onRevokeRoutine = vi.fn();

      render(
        <McpPinsAndRoutinesPanel
          mcpPins={SAMPLE_MCP_PINS}
          routines={SAMPLE_ROUTINES}
          onReapprovePin={onReapprovePin}
          onCreateRoutine={onCreateRoutine}
          onPauseRoutine={onPauseRoutine}
          onRevokeRoutine={onRevokeRoutine}
        />
      );

      // Verify MCP pins & SHA-256 hashes
      expect(
        screen.getByTestId('mcp-pin-hash-pin-withings-1')
      ).toHaveTextContent('SHA-256: e3b0c44298fc1c149afbf4c8996fb924');
      expect(
        screen.getByTestId('mcp-pin-taint-badge-pin-withings-1')
      ).toHaveTextContent('Untrusted Output (Taint)');
      expect(
        screen.getByTestId('mcp-pin-status-pin-withings-1')
      ).toHaveTextContent('pinned');

      // Verify drift-blocked pin shows Re-approve Schema button
      expect(screen.getByTestId('mcp-pin-status-pin-fhir-2')).toHaveTextContent(
        'drift_blocked'
      );
      fireEvent.click(screen.getByTestId('mcp-pin-reapprove-btn-pin-fhir-2'));
      expect(onReapprovePin).toHaveBeenCalledWith(
        'pin-fhir-2',
        '9f86d081884c7d659a2feaa0c55ad015'
      );

      // Verify A2 standing routine fire-time re-check notice & expiry badge
      expect(
        screen.getByTestId('routine-fire-recheck-notice')
      ).toHaveTextContent(
        'Re-verifies creator access, active consent, and untainted state at fire time'
      );
      expect(
        screen.getByTestId('routine-expiry-badge-rt-101')
      ).toHaveTextContent(/<= 90 days max|≤ 90 days max/i);

      // Trigger Pause & Revoke on routine
      fireEvent.click(screen.getByTestId('routine-pause-btn-rt-101'));
      expect(onPauseRoutine).toHaveBeenCalledWith('rt-101');

      fireEvent.click(screen.getByTestId('routine-revoke-btn-rt-101'));
      expect(onRevokeRoutine).toHaveBeenCalledWith('rt-101');

      // Test > 90 days validation rejection
      fireEvent.change(screen.getByTestId('routine-expiry-days-input'), {
        target: { value: '120' },
      });
      fireEvent.submit(screen.getByTestId('create-routine-form'));
      expect(screen.getByTestId('routine-expiry-error')).toHaveTextContent(
        /must expire within 1 to 90 days/i
      );
      expect(onCreateRoutine).not.toHaveBeenCalled();

      // Test valid <= 90 days submission
      fireEvent.change(screen.getByTestId('routine-expiry-days-input'), {
        target: { value: '45' },
      });
      fireEvent.submit(screen.getByTestId('create-routine-form'));

      await waitFor(() => {
        expect(onCreateRoutine).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'Morning BP & Vitals Digest',
            tool_name: 'withings.fetch_daily_vitals',
            expires_in_days: 45,
          })
        );
      });
    });
  });

  describe('2. EmailDraftsAndSchoolFeedsPanel Component (AU-59, AU-60, AU-61)', () => {
    it('renders Gmail read-only staging queue, No-Auto-Send email drafts with mailto/.eml actions, and school .ics feeds', async () => {
      const onConfirmGmailCandidate = vi.fn();
      const onCreateEmailDraft = vi.fn();
      const onDownloadEmailEml = vi.fn();
      const onCreateSchoolFeed = vi.fn();
      const onSyncSchoolFeed = vi.fn();

      render(
        <EmailDraftsAndSchoolFeedsPanel
          gmailCandidates={SAMPLE_GMAIL_CANDIDATES}
          emailDrafts={SAMPLE_EMAIL_DRAFTS}
          schoolFeeds={SAMPLE_SCHOOL_FEEDS}
          onConfirmGmailCandidate={onConfirmGmailCandidate}
          onCreateEmailDraft={onCreateEmailDraft}
          onDownloadEmailEml={onDownloadEmailEml}
          onCreateSchoolFeed={onCreateSchoolFeed}
          onSyncSchoolFeed={onSyncSchoolFeed}
        />
      );

      // Verify Gmail read-only scope & provenance
      expect(
        screen.getByTestId('gmail-readonly-scope-badge')
      ).toHaveTextContent('Scope: gmail.readonly (No Send Scope)');
      expect(
        screen.getByTestId('gmail-candidate-provenance-0')
      ).toHaveTextContent('From Gmail, Oct 13 (Pediatric Dental Clinic)');
      expect(screen.getByTestId('gmail-candidate-taint-0')).toHaveTextContent(
        'Untrusted (untrusted)'
      );

      // Confirm staged Gmail candidate 0
      fireEvent.click(screen.getByTestId('gmail-confirm-btn-0'));
      expect(onConfirmGmailCandidate).toHaveBeenCalledWith(0);

      // Candidate 1 is already confirmed
      expect(screen.getByTestId('gmail-confirmed-badge-1')).toHaveTextContent(
        'Confirmed'
      );

      // Verify Email Drafts No Auto-Send badge, mailto link, and .eml download
      expect(screen.getByTestId('email-no-autosend-badge')).toHaveTextContent(
        'No Auto-Send (User Sends from Mail Client)'
      );
      expect(
        screen.getByTestId('email-mailto-link-draft-301')
      ).toHaveAttribute(
        'href',
        'mailto:nurse@oakridge.edu?subject=Signed%20Asthma%20Action%20Plan%20Attached'
      );
      fireEvent.click(screen.getByTestId('email-download-eml-btn-draft-301'));
      expect(onDownloadEmailEml).toHaveBeenCalledWith('draft-301');

      // Submit new email draft
      fireEvent.submit(screen.getByTestId('create-email-draft-form'));
      await waitFor(() => {
        expect(onCreateEmailDraft).toHaveBeenCalledWith(
          expect.objectContaining({
            recipient: 'records@pediatrics.example.org',
            subject: 'Immunization Form Request',
          })
        );
      });

      // Verify School .ics feeds & Sync button
      expect(
        screen.getByTestId('school-feed-events-feed-401')
      ).toHaveTextContent('6 events synced');
      fireEvent.click(screen.getByTestId('school-feed-sync-btn-feed-401'));
      expect(onSyncSchoolFeed).toHaveBeenCalledWith('feed-401');

      // Subscribe new school .ics feed
      fireEvent.submit(screen.getByTestId('create-school-feed-form'));
      await waitFor(() => {
        expect(onCreateSchoolFeed).toHaveBeenCalledWith({
          label: 'Oakridge Elementary Calendar',
          feed_url: 'https://calendar.oakridge.edu/school-events.ics',
        });
      });
    });
  });

  describe('3. CompanionAndHandoverPanel Component (AU-62 & AU-63)', () => {
    it('renders iOS Companion TLS fingerprint pinning, viewer section permissions, and Teen Handover DEK rotation wizard', async () => {
      const onGeneratePairingQr = vi.fn();
      const onRevokeCompanionDevice = vi.fn();
      const onSaveViewerSections = vi.fn();
      const onExecuteTeenHandover = vi.fn();

      const handoverResult: TeenHandoverResponse = {
        profile_id: 'prof-1',
        new_steward_user_id: 'user-teen-1',
        new_dek_version: 2,
        kept_connections: ['conn-withings-1'],
        revoked_connections: ['conn-epic-1'],
      };

      render(
        <CompanionAndHandoverPanel
          companionDevices={SAMPLE_COMPANION_DEVICES}
          pairingQr={SAMPLE_PAIRING_QR}
          connections={SAMPLE_CONNECTIONS}
          handoverResult={handoverResult}
          onGeneratePairingQr={onGeneratePairingQr}
          onRevokeCompanionDevice={onRevokeCompanionDevice}
          onSaveViewerSections={onSaveViewerSections}
          onExecuteTeenHandover={onExecuteTeenHandover}
        />
      );

      // Verify iOS Companion Mode S guard & TLS SHA-256 fingerprint
      expect(
        screen.getByTestId('companion-mode-s-guard-badge')
      ).toHaveTextContent('Mode S / TLS Cert Fingerprint Pinning Active');
      expect(
        screen.getByTestId('companion-cert-fingerprint-dev-501')
      ).toHaveTextContent(/TLS SHA-256: A1:B2:C3:D4/);

      // Trigger Generate Pairing QR & verify QR code display
      fireEvent.click(screen.getByTestId('companion-generate-qr-btn'));
      expect(onGeneratePairingQr).toHaveBeenCalledWith(
        'iPhone 16 Pro (Apple Health)',
        ['vitals', 'clinical_records', 'reminders']
      );
      expect(screen.getByTestId('companion-qr-code')).toHaveTextContent(
        'CF-884-921'
      );
      expect(screen.getByTestId('companion-qr-fingerprint')).toHaveTextContent(
        /Pinned TLS Cert SHA-256: A1:B2:C3:D4/
      );

      // Trigger Revoke Companion Device
      fireEvent.click(screen.getByTestId('companion-revoke-btn-dev-501'));
      expect(onRevokeCompanionDevice).toHaveBeenCalledWith('dev-501');

      // Verify Viewer Section Checkboxes (connections and notes unchecked by default)
      expect(
        screen.getByTestId('viewer-section-checkbox-appointments')
      ).toBeChecked();
      expect(
        screen.getByTestId('viewer-section-checkbox-connections')
      ).not.toBeChecked();

      // Toggle 'vitals' on and save
      fireEvent.click(screen.getByTestId('viewer-section-checkbox-vitals'));
      fireEvent.click(screen.getByTestId('viewer-sections-save-btn'));
      expect(onSaveViewerSections).toHaveBeenCalledWith('user-grandparent-1', [
        'appointments',
        'reminders',
        'vitals',
      ]);

      // Teen Handover Wizard: set conn-epic-1 to revoke and execute
      fireEvent.click(screen.getByTestId('teen-handover-revoke-conn-epic-1'));
      fireEvent.click(screen.getByTestId('teen-handover-execute-btn'));

      expect(onExecuteTeenHandover).toHaveBeenCalledWith({
        new_steward_user_id: 'user-teen-1',
        connection_decisions: {
          'conn-withings-1': 'keep',
          'conn-epic-1': 'revoke',
        },
      });

      // Verify rotated DEK version banner
      expect(
        screen.getByTestId('teen-handover-dek-result')
      ).toHaveTextContent('Rotated to Vault DEK v2');
    });
  });

  describe('4. ConnectionsHub Multi-Tab Integration', () => {
    it('switches across Connections, MCP Pins & Routines, Gmail/Drafts/School Feeds, and iOS Companion/Teen Handover tabs', () => {
      render(
        <ConnectionsHub
          connectors={SAMPLE_CONNECTORS}
          connections={SAMPLE_CONNECTIONS}
          mcpPins={SAMPLE_MCP_PINS}
          routines={SAMPLE_ROUTINES}
          gmailCandidates={SAMPLE_GMAIL_CANDIDATES}
          emailDrafts={SAMPLE_EMAIL_DRAFTS}
          schoolFeeds={SAMPLE_SCHOOL_FEEDS}
          companionDevices={SAMPLE_COMPANION_DEVICES}
        />
      );

      // Default tab is connections
      expect(
        screen.getByTestId('starter-connector-card-withings')
      ).toBeInTheDocument();

      // Switch to MCP Pins & A2 Routines
      fireEvent.click(screen.getByTestId('hub-tab-mcp-routines'));
      expect(
        screen.getByTestId('mcp-pins-and-routines-panel')
      ).toBeInTheDocument();

      // Switch to Gmail, Drafts & School Feeds
      fireEvent.click(screen.getByTestId('hub-tab-email-school'));
      expect(
        screen.getByTestId('email-drafts-and-school-feeds-panel')
      ).toBeInTheDocument();

      // Switch to iOS Companion & Teen Handover
      fireEvent.click(screen.getByTestId('hub-tab-companion-handover'));
      expect(
        screen.getByTestId('companion-and-handover-panel')
      ).toBeInTheDocument();
    });
  });

  describe('5. Autonomy Batch 6 API Client Helpers', () => {
    it('invokes expected /api/v1/profiles/:profileId endpoints for MCP pins, routines, Gmail staging, drafts, school feeds, companion, and handover', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({}),
      } as Response);

      await fetchMcpToolPins('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/mcp-pins',
        expect.objectContaining({ credentials: 'include' })
      );

      await reapproveMcpToolPin('prof-1', 'pin-1', 'hash-abc');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/mcp-pins/pin-1/reapprove',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ schema_hash: 'hash-abc' }),
        })
      );

      await fetchStandingRoutines('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/routines',
        expect.objectContaining({ credentials: 'include' })
      );

      await createStandingRoutine('prof-1', {
        connection_id: 'conn-1',
        name: 'Daily BP',
        tool_name: 'withings.fetch_daily_vitals',
        rrule: 'FREQ=DAILY;BYHOUR=7',
        timezone: 'America/Chicago',
        expires_in_days: 30,
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/routines',
        expect.objectContaining({ method: 'POST' })
      );

      await pauseStandingRoutine('prof-1', 'rt-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/routines/rt-1/pause',
        expect.objectContaining({ method: 'POST' })
      );

      await revokeStandingRoutine('prof-1', 'rt-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/routines/rt-1/revoke',
        expect.objectContaining({ method: 'POST' })
      );

      await fetchGmailStagedCandidates('prof-1', 'conn-gmail-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-gmail-1/gmail-staged',
        expect.objectContaining({ credentials: 'include' })
      );

      await confirmGmailStagedCandidate('prof-1', 'conn-gmail-1', 0);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-gmail-1/gmail-confirm',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ candidate_index: 0 }),
        })
      );

      await fetchEmailDrafts('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/email-drafts',
        expect.objectContaining({ credentials: 'include' })
      );

      await createEmailDraft('prof-1', {
        recipient: 'clinic@example.org',
        subject: 'Records',
        body: 'Requesting records',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/email-drafts',
        expect.objectContaining({ method: 'POST' })
      );

      await downloadEmailDraftEml('prof-1', 'draft-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/email-drafts/draft-1/eml',
        expect.objectContaining({ credentials: 'include' })
      );

      await fetchSchoolIcsFeeds('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/school-feeds',
        expect.objectContaining({ credentials: 'include' })
      );

      await createSchoolIcsFeed('prof-1', {
        label: 'School',
        feed_url: 'https://school.edu/cal.ics',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/school-feeds',
        expect.objectContaining({ method: 'POST' })
      );

      await syncSchoolIcsFeed('prof-1', 'feed-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/school-feeds/feed-1/sync',
        expect.objectContaining({ method: 'POST' })
      );

      await fetchCompanionDevices('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/companion/devices',
        expect.objectContaining({ credentials: 'include' })
      );

      await generateCompanionPairingQr('prof-1', 'iPhone', ['vitals']);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/companion/pair',
        expect.objectContaining({ method: 'POST' })
      );

      await revokeCompanionDevice('prof-1', 'dev-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/companion/devices/dev-1/revoke',
        expect.objectContaining({ method: 'POST' })
      );

      await fetchViewerSectionPermissions('prof-1', 'viewer-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/viewers/viewer-1/sections',
        expect.objectContaining({ credentials: 'include' })
      );

      await updateViewerSectionPermissions('prof-1', 'viewer-1', [
        'appointments',
      ]);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/viewers/viewer-1/sections',
        expect.objectContaining({
          method: 'PUT',
          body: JSON.stringify({ allowed_sections: ['appointments'] }),
        })
      );

      await executeTeenHandover('prof-1', {
        new_steward_user_id: 'teen-1',
        connection_decisions: { 'conn-1': 'keep' },
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/handover/teen',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });
});
