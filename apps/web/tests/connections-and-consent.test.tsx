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
  ConnectorConsentModal,
  SyncHealthTable,
  DataFlowsPanel,
  ConnectionsHub,
} from '@/components/connections';
import {
  fetchConnectorCatalog,
  fetchProfileConnections,
  createProfileConnection,
  completeOAuthCallback,
  triggerConnectionSync,
  fetchConnectionSyncRuns,
  revokeProfileConnection,
  fetchProfileConsents,
  fetchProfileDataFlows,
} from '@/lib/connectionsClient';
import type {
  ConnectionItem,
  ConnectorManifestSummary,
  DataFlowsInventory,
  SyncRunItem,
} from '@/types/connections';

const STARTER_CONNECTORS: ConnectorManifestSummary[] = [
  {
    id: 'withings',
    name: 'Withings Health Mate',
    version: '1.0.0',
    description:
      'Blood pressure monitors, smart scales, and sleep analyzers via Withings OAuth2 API.',
    categories: ['vitals', 'activity'],
    allowed_hosts: ['wbsapi.withings.net', 'account.withings.com'],
    scopes: ['user.metrics', 'user.activity'],
    auth_type: 'oauth2',
    pkce: true,
    client_source: 'byo_or_system',
    trust_level: 'trusted_device',
  },
  {
    id: 'google_calendar',
    name: 'Google Calendar / CalDAV',
    version: '1.0.0',
    description:
      'Two-way clinical appointment reminders and care schedule synchronization.',
    categories: ['calendar', 'appointments'],
    allowed_hosts: ['www.googleapis.com', 'oauth2.googleapis.com'],
    scopes: ['https://www.googleapis.com/auth/calendar.events'],
    auth_type: 'oauth2',
    pkce: true,
    client_source: 'byo_or_system',
    trust_level: 'trusted_device',
  },
  {
    id: 'epic_mychart_fhir',
    name: 'Epic MyChart SMART on FHIR',
    version: '1.0.0',
    description:
      'Patient-authorized SMART on FHIR R4 clinical records, labs, medications, and immunizations.',
    categories: ['clinical_records', 'medications', 'immunizations'],
    allowed_hosts: ['fhir.epic.com'],
    scopes: ['launch/patient', 'patient/*.read', 'openid', 'fhirUser'],
    auth_type: 'smart_on_fhir',
    pkce: true,
    client_source: 'byo_or_system',
    trust_level: 'untrusted_external',
  },
];

const SAMPLE_SYNC_RUNS: SyncRunItem[] = [
  {
    id: 'run-201',
    connection_id: 'conn-withings-1',
    connector_id: 'withings',
    stream: 'vitals.blood_pressure',
    status: 'succeeded',
    records_fetched: 14,
    records_upserted: 14,
    records_quarantined: 0,
    started_at: '2026-10-13T09:00:00Z',
    completed_at: '2026-10-13T09:00:01Z',
    duration_ms: 420,
  },
  {
    id: 'run-202',
    connection_id: 'conn-epic-1',
    connector_id: 'epic_mychart_fhir',
    stream: 'fhir.Observation',
    status: 'partial',
    records_fetched: 10,
    records_upserted: 8,
    records_quarantined: 2,
    error_code: 'SCHEMA_QUARANTINE',
    error_message: '2 Observation records lacked valid numeric unit coding.',
    started_at: '2026-10-13T10:15:00Z',
    completed_at: '2026-10-13T10:15:02Z',
    duration_ms: 915,
  },
];

const SAMPLE_CONNECTIONS: ConnectionItem[] = [
  {
    id: 'conn-withings-1',
    profile_id: 'prof-1',
    connector_id: 'withings',
    label: 'Home Withings BPM Connect',
    status: 'active',
    status_message: 'Healthy sync',
    consecutive_failures: 0,
    consented_version: '1.0.0',
    last_sync_at: '2026-10-13T09:00:01Z',
    created_at: '2026-10-01T08:00:00Z',
    latest_sync_run: SAMPLE_SYNC_RUNS[0],
  },
  {
    id: 'conn-gcal-1',
    profile_id: 'prof-1',
    connector_id: 'google_calendar',
    label: 'Family Care Calendar',
    status: 'degraded',
    status_message: 'Upstream rate limit encountered on calendar poll.',
    consecutive_failures: 3,
    consented_version: '1.0.0',
    last_sync_at: '2026-10-13T07:30:00Z',
    created_at: '2026-10-02T08:00:00Z',
  },
  {
    id: 'conn-epic-1',
    profile_id: 'prof-1',
    connector_id: 'epic_mychart_fhir',
    label: 'Hospital Epic MyChart',
    status: 'needs_reauth',
    status_message: 'Refresh token expired or revoked by upstream authorization server.',
    consecutive_failures: 5,
    consented_version: '1.0.0',
    last_sync_at: '2026-10-12T18:00:00Z',
    created_at: '2026-10-03T08:00:00Z',
    latest_sync_run: SAMPLE_SYNC_RUNS[1],
  },
];

const SAMPLE_DATA_FLOWS: DataFlowsInventory = {
  profile_id: 'prof-1',
  model_provider: {
    provider: 'Ollama (llama3.2)',
    host: 'http://127.0.0.1:11434',
    is_local: true,
    connector_context_policy:
      'Local-default inference enforced when connector data is in context.',
  },
  search_provider: {
    provider: 'DuckDuckGo Medical Allowlist',
    allowed_hosts: ['api.duckduckgo.com', 'medlineplus.gov'],
    phi_sanitiser_enabled: true,
    status: 'active',
  },
  connections: [
    {
      connection_id: 'conn-withings-1',
      connector_id: 'withings',
      connector_name: 'Withings Health Mate',
      label: 'Home Withings BPM Connect',
      status: 'active',
      allowed_hosts: ['wbsapi.withings.net', 'account.withings.com'],
      categories: ['vitals', 'activity'],
      terms_version: '2026-10-01',
      connector_version: '1.0.0',
    },
  ],
};

describe('External Connections, Granular Consent, Sync Health, and Data Flows Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  describe('1. ConnectorConsentModal Component', () => {
    it('displays categories, outbound hosts, trust badge, BYO client inputs, and submits consent payload without browser storage', async () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();

      const { rerender } = render(
        <ConnectorConsentModal
          connector={STARTER_CONNECTORS[0]}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );

      expect(screen.getByTestId('connector-consent-modal')).toBeInTheDocument();
      expect(screen.getByTestId('consent-trust-badge')).toHaveTextContent(
        'Trusted Structured Device Data'
      );

      // Verify categories & hosts
      expect(
        screen.getByTestId('consent-category-checkbox-vitals')
      ).toBeChecked();
      expect(
        screen.getByTestId('consent-host-badge-wbsapi.withings.net')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('consent-vault-security-notice')
      ).toHaveTextContent(/Encrypted in your local Carefold Vault via AES-256-GCM/i);

      // Verify untrusted external clinical narrative badge on Epic MyChart SMART on FHIR
      rerender(
        <ConnectorConsentModal
          connector={STARTER_CONNECTORS[2]}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );
      expect(screen.getByTestId('consent-trust-badge')).toHaveTextContent(
        'Untrusted External Clinical Narrative — Taint Enabled'
      );

      // Enter BYO credentials and submit
      fireEvent.change(screen.getByTestId('consent-byo-client-id'), {
        target: { value: 'byo-epic-client-id' },
      });
      fireEvent.change(screen.getByTestId('consent-byo-client-secret'), {
        target: { value: 'byo-epic-secret-xyz' },
      });

      fireEvent.click(screen.getByTestId('consent-confirm-btn'));

      await waitFor(() => {
        expect(onConfirm).toHaveBeenCalledWith(
          expect.objectContaining({
            connector_id: 'epic_mychart_fhir',
            categories: ['clinical_records', 'medications', 'immunizations'],
            terms_version: '2026-10-01',
            client_id: 'byo-epic-client-id',
            client_secret: 'byo-epic-secret-xyz',
          })
        );
      });

      // Verify zero secrets stored in browser storage
      expect(window.localStorage.length).toBe(0);
      expect(window.sessionStorage.length).toBe(0);
    });
  });

  describe('2. ConnectionsHub Component', () => {
    it('renders the 3 starter connectors, status badges, triggers Sync Now, and executes the Revoke Cascade with deleteImportedData=true', async () => {
      const onSyncNow = vi.fn();
      const onRevokeConnection = vi.fn();
      const onReauthenticate = vi.fn();

      render(
        <ConnectionsHub
          connectors={STARTER_CONNECTORS}
          connections={SAMPLE_CONNECTIONS}
          syncRunsByConnection={{ 'conn-epic-1': [SAMPLE_SYNC_RUNS[1]] }}
          dataFlows={SAMPLE_DATA_FLOWS}
          onSyncNow={onSyncNow}
          onRevokeConnection={onRevokeConnection}
          onReauthenticate={onReauthenticate}
        />
      );

      // Verify 3 Capped v1 Starter Connectors
      expect(
        screen.getByTestId('starter-connector-card-withings')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('starter-connector-card-google_calendar')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('starter-connector-card-epic_mychart_fhir')
      ).toBeInTheDocument();

      // Verify degradation alert banner
      expect(
        screen.getByTestId('connections-degradation-banner')
      ).toBeInTheDocument();

      // Verify status badges: active, degraded, needs_reauth
      expect(
        screen.getByTestId('connection-status-badge-conn-withings-1')
      ).toHaveTextContent('active');
      expect(
        screen.getByTestId('connection-status-badge-conn-gcal-1')
      ).toHaveTextContent('degraded');
      expect(
        screen.getByTestId('connection-status-badge-conn-epic-1')
      ).toHaveTextContent('needs_reauth');

      // Trigger Sync Now
      fireEvent.click(screen.getByTestId('sync-now-btn-conn-withings-1'));
      expect(onSyncNow).toHaveBeenCalledWith('conn-withings-1');

      // Trigger Re-authenticate on needs_reauth connection
      fireEvent.click(screen.getByTestId('reauth-btn-conn-epic-1'));
      expect(onReauthenticate).toHaveBeenCalledWith(SAMPLE_CONNECTIONS[2]);

      // Toggle Sync Health Table
      fireEvent.click(
        screen.getByTestId('toggle-sync-health-btn-conn-epic-1')
      );
      expect(screen.getByTestId('sync-health-table')).toBeInTheDocument();

      // Open Disconnect / Revoke Modal & check "Also delete all records imported from this connection"
      fireEvent.click(
        screen.getByTestId('open-revoke-modal-btn-conn-withings-1')
      );
      expect(screen.getByTestId('revoke-connection-modal')).toBeInTheDocument();

      fireEvent.click(screen.getByTestId('revoke-delete-imported-checkbox'));
      fireEvent.click(screen.getByTestId('confirm-revoke-btn'));

      await waitFor(() => {
        expect(onRevokeConnection).toHaveBeenCalledWith(
          'conn-withings-1',
          true
        );
      });
    });
  });

  describe('3. SyncHealthTable Component', () => {
    it('renders fetched, upserted, and quarantined record counts and error alerts', () => {
      render(
        <SyncHealthTable
          runs={SAMPLE_SYNC_RUNS}
          connectionLabel="Hospital Epic MyChart"
        />
      );

      expect(screen.getByTestId('sync-health-table')).toBeInTheDocument();
      expect(screen.getByTestId('sync-run-status-run-201')).toHaveTextContent(
        'succeeded'
      );
      expect(screen.getByTestId('sync-run-fetched-run-201')).toHaveTextContent(
        '14'
      );
      expect(screen.getByTestId('sync-run-upserted-run-201')).toHaveTextContent(
        '14'
      );
      expect(
        screen.getByTestId('sync-run-quarantined-run-201')
      ).toHaveTextContent('0');

      expect(screen.getByTestId('sync-run-status-run-202')).toHaveTextContent(
        'partial'
      );
      expect(screen.getByTestId('sync-run-fetched-run-202')).toHaveTextContent(
        '10'
      );
      expect(screen.getByTestId('sync-run-upserted-run-202')).toHaveTextContent(
        '8'
      );
      expect(
        screen.getByTestId('sync-run-quarantined-run-202')
      ).toHaveTextContent('2');
      expect(screen.getByTestId('sync-run-error-run-202')).toHaveTextContent(
        /SCHEMA_QUARANTINE/i
      );
    });
  });

  describe('4. DataFlowsPanel Component', () => {
    it('displays model provider, search sanitiser status, and connector outbound hosts', () => {
      const onQuickRevoke = vi.fn();

      render(
        <DataFlowsPanel
          inventory={SAMPLE_DATA_FLOWS}
          onQuickRevoke={onQuickRevoke}
        />
      );

      expect(screen.getByTestId('data-flows-panel')).toBeInTheDocument();
      expect(screen.getByTestId('data-flows-model-name')).toHaveTextContent(
        'Ollama (llama3.2)'
      );
      expect(
        screen.getByTestId('data-flows-model-locality-badge')
      ).toHaveTextContent('Local-Default Active');
      expect(
        screen.getByTestId('data-flows-phi-sanitiser-badge')
      ).toHaveTextContent('PHI Query Sanitiser Active');
      expect(
        screen.getByTestId('data-flow-hosts-conn-withings-1')
      ).toHaveTextContent('wbsapi.withings.net');
      expect(
        screen.getByTestId('data-flow-categories-conn-withings-1')
      ).toHaveTextContent('vitals');

      fireEvent.click(
        screen.getByTestId('data-flow-revoke-btn-conn-withings-1')
      );
      expect(onQuickRevoke).toHaveBeenCalledWith('conn-withings-1');
    });
  });

  describe('5. Connections & Consent API Client Helpers', () => {
    it('invokes expected /api/v1/connectors and /api/v1/profiles/:profileId endpoints', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({}),
      } as Response);

      await fetchConnectorCatalog();
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/connectors',
        expect.objectContaining({ credentials: 'include' })
      );

      await fetchProfileConnections('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections',
        expect.objectContaining({ credentials: 'include' })
      );

      await createProfileConnection('prof-1', {
        connector_id: 'withings',
        categories: ['vitals'],
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections',
        expect.objectContaining({ method: 'POST' })
      );

      await completeOAuthCallback('prof-1', 'conn-1', {
        code: 'auth-code-123',
        state: 'state-xyz',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-1/oauth/callback',
        expect.objectContaining({ method: 'POST' })
      );

      await triggerConnectionSync('prof-1', 'conn-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-1/sync',
        expect.objectContaining({ method: 'POST' })
      );

      await fetchConnectionSyncRuns('prof-1', 'conn-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-1/sync-runs',
        expect.objectContaining({ credentials: 'include' })
      );

      await revokeProfileConnection('prof-1', 'conn-1', true);
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/connections/conn-1/revoke',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ delete_imported_data: true }),
        })
      );

      await fetchProfileConsents('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/consents',
        expect.objectContaining({ credentials: 'include' })
      );

      await fetchProfileDataFlows('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/data-flows',
        expect.objectContaining({ credentials: 'include' })
      );
    });
  });
});
