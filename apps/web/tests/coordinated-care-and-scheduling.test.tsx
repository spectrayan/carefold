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

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { CoordinatedV2Panel, ConnectionsHub } from '@/components/connections';
import {
  verifySmartHealthCard,
  discoverSmartSchedulingSlots,
  previewZocdocBooking,
  verifyProfileAuditChain,
  fetchOsServiceDescriptors,
  fetchV2ConnectorCatalog,
} from '@/lib/coordinatedCareClient';
import type {
  AuditChainVerificationResponse,
  OsServiceDescriptorItem,
  SmartHealthCardVerificationResult,
  SmartSchedulingSlotItem,
  V2ConnectorSummary,
  ZocdocBookingPreview,
} from '@/types/coordinatedCare';
import type {
  ConnectionItem,
  ConnectorManifestSummary,
} from '@/types/connections';

const SAMPLE_SHC_VERIFIED: SmartHealthCardVerificationResult = {
  batch_id: 'batch-shc-01',
  verification_status: 'verified',
  issuer: 'https://smarthealth.cards/examples/issuer',
  records_count: 2,
  summary: {
    immunisations: 1,
    observations: 1,
  },
  staged_records: [
    {
      resource_type: 'Immunization',
      display: 'MMR Vaccine Dose 2',
      effective_at: '2026-09-15',
      source_display:
        'From SMART Health Card (https://smarthealth.cards/examples/issuer) [verified]',
      trust: 'untrusted',
    },
    {
      resource_type: 'Observation',
      display: 'SARS-CoV-2 IgG Qualitative',
      effective_at: '2026-09-16',
      source_display:
        'From SMART Health Card (https://smarthealth.cards/examples/issuer) [verified]',
      trust: 'untrusted',
    },
  ],
};

const SAMPLE_SHC_UNVERIFIED: SmartHealthCardVerificationResult = {
  ...SAMPLE_SHC_VERIFIED,
  verification_status: 'unverified_issuer',
  issuer: 'https://unknown-clinic.example.org/shc',
};

const SAMPLE_SMART_SLOTS: SmartSchedulingSlotItem[] = [
  {
    slot_id: 'slot-ped-101',
    provider_name: 'Dr. Elena Rostova, MD',
    specialty: 'pediatrics',
    location: 'Northside Children Clinic',
    start_time: '2026-10-20T14:00:00Z',
    end_time: '2026-10-20T14:30:00Z',
    fits_calendar: true,
    booking_url: 'https://scheduling.example.org/book/slot-ped-101',
    source: 'smart_scheduling_links',
  },
  {
    slot_id: 'slot-zocdoc-202',
    provider_name: 'Dr. Marcus Vance, DDS',
    specialty: 'pediatric_dentistry',
    location: 'Downtown Pediatric Dental',
    start_time: '2026-10-21T09:00:00Z',
    end_time: '2026-10-21T09:45:00Z',
    fits_calendar: false,
    booking_url: 'https://www.zocdoc.com/booking/slot-zocdoc-202',
    source: 'zocdoc',
  },
];

const SAMPLE_ZOCDOC_PREVIEW: ZocdocBookingPreview = {
  provider_id: 'prov-slot-zocdoc-202',
  provider_name: 'Dr. Marcus Vance, DDS',
  specialty: 'pediatric_dentistry',
  slot_id: 'slot-zocdoc-202',
  start_time: '2026-10-21T09:00:00Z',
  insurance_carrier: 'BlueCross BlueShield',
  risk_tier: 'irreversible',
  requires_approval: true,
  payload_hash:
    'a3f5c8e1d9b04762819203847561928374650192837465019283746501928374',
  status: 'approval_required',
};

const SAMPLE_V2_CONNECTORS: V2ConnectorSummary[] = [
  {
    id: 'oracle_health_smart',
    name: 'Oracle Health (SMART R4)',
    category: 'ehr_smart',
    trust_level: 'untrusted',
    risk_tier: 'read',
    allowed_hosts: ['fhir-myrecord.cerner.com'],
  },
  {
    id: 'athenahealth_smart',
    name: 'athenahealth (SMART R4)',
    category: 'ehr_smart',
    trust_level: 'untrusted',
    risk_tier: 'read',
    allowed_hosts: ['api.platform.athenahealth.com'],
  },
  {
    id: 'cms_blue_button_2',
    name: 'CMS Blue Button 2.0 (EOB Claims)',
    category: 'payer',
    trust_level: 'untrusted',
    risk_tier: 'read',
    allowed_hosts: ['api.bluebutton.cms.gov'],
  },
  {
    id: 'oura_ring_v2',
    name: 'Oura Ring (Daily Sleep/HRV)',
    category: 'wearable',
    trust_level: 'trusted',
    risk_tier: 'read',
    allowed_hosts: ['api.ouraring.com'],
  },
  {
    id: 'google_health_connect',
    name: 'Google Health Connect',
    category: 'wearable',
    trust_level: 'trusted',
    risk_tier: 'read',
    allowed_hosts: ['healthconnect.googleapis.com'],
  },
  {
    id: 'microsoft_graph_calendar',
    name: 'Microsoft Graph Calendar',
    category: 'calendar',
    trust_level: 'untrusted',
    risk_tier: 'write_external',
    allowed_hosts: ['graph.microsoft.com'],
  },
];

const SAMPLE_AUDIT_INTACT: AuditChainVerificationResponse = {
  profile_id: 'prof-1',
  valid: true,
  checked_count: 14,
  head_hash: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
  broken_at_event_id: null,
  reason: null,
};

const SAMPLE_AUDIT_BROKEN: AuditChainVerificationResponse = {
  profile_id: 'prof-1',
  valid: false,
  checked_count: 14,
  head_hash: '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069',
  broken_at_event_id: 'evt-tampered-99',
  reason: 'entry_hash mismatch on audit row evt-tampered-99',
};

const SAMPLE_SERVICE_DESCRIPTORS: OsServiceDescriptorItem[] = [
  {
    platform: 'macos_launchd',
    filename: 'com.carefold.runtime.plist',
    install_path: '~/Library/LaunchAgents/com.carefold.runtime.plist',
    content: '<plist version="1.0"><string>127.0.0.1</string></plist>',
    install_command:
      'launchctl load -w ~/Library/LaunchAgents/com.carefold.runtime.plist',
  },
  {
    platform: 'linux_systemd',
    filename: 'carefold-runtime.service',
    install_path: '~/.config/systemd/user/carefold-runtime.service',
    content: '[Service]\nExecStart=carefold serve --host 127.0.0.1',
    install_command: 'systemctl --user enable --now carefold-runtime.service',
  },
  {
    platform: 'windows_task_scheduler',
    filename: 'CarefoldRuntimeTask.xml',
    install_path: '%LOCALAPPDATA%\\Carefold\\CarefoldRuntimeTask.xml',
    content: '<Task><Arguments>--host 127.0.0.1</Arguments></Task>',
    install_command:
      'schtasks /Create /TN "CarefoldRuntime" /XML "%LOCALAPPDATA%\\Carefold\\CarefoldRuntimeTask.xml" /F',
  },
];

describe('Coordinated v2 Experience & Autonomy Batch 7 Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('1. SMART Health Card JWS Verifier (AU-77)', () => {
    it('verifies ES256 signature badge, issuer display, staged counts, and triggers Verify & Stage callback', async () => {
      const onVerifySmartHealthCard = vi.fn();

      const { rerender } = render(
        <CoordinatedV2Panel
          shcResult={SAMPLE_SHC_VERIFIED}
          onVerifySmartHealthCard={onVerifySmartHealthCard}
        />
      );

      expect(screen.getByTestId('shc-verification-badge')).toHaveTextContent(
        'ES256 Signature Verified'
      );
      expect(screen.getByTestId('shc-issuer-uri')).toHaveTextContent(
        'Issuer: https://smarthealth.cards/examples/issuer'
      );
      expect(screen.getByTestId('shc-summary-counts')).toHaveTextContent(
        'Staged: 1 immunisations, 1 observations'
      );
      expect(screen.getByTestId('shc-staged-records-list')).toHaveTextContent(
        'MMR Vaccine Dose 2'
      );

      fireEvent.change(screen.getByTestId('shc-payload-input'), {
        target: { value: 'shc:/112233445566' },
      });
      fireEvent.submit(screen.getByTestId('shc-verify-form'));

      await waitFor(() => {
        expect(onVerifySmartHealthCard).toHaveBeenCalledWith({
          filename: 'immunization.smart-health-card',
          content: 'shc:/112233445566',
        });
      });

      // Rerender with unverified issuer
      rerender(
        <CoordinatedV2Panel
          shcResult={SAMPLE_SHC_UNVERIFIED}
          onVerifySmartHealthCard={onVerifySmartHealthCard}
        />
      );
      expect(screen.getByTestId('shc-verification-badge')).toHaveTextContent(
        'Unverified Issuer'
      );
    });
  });

  describe('2. SMART Scheduling Links & Zocdoc Irreversible Booking Flow (AU-71 & AU-72)', () => {
    it('renders Fits Calendar / Calendar Conflict badges and enforces Zocdoc irreversible booking approval', async () => {
      const onDiscoverSmartSlots = vi.fn();
      const onRequestZocdocApproval = vi.fn();

      render(
        <CoordinatedV2Panel
          smartSlots={SAMPLE_SMART_SLOTS}
          zocdocPreview={SAMPLE_ZOCDOC_PREVIEW}
          onDiscoverSmartSlots={onDiscoverSmartSlots}
          onRequestZocdocApproval={onRequestZocdocApproval}
        />
      );

      // Verify Zocdoc irreversible badge
      expect(screen.getByTestId('zocdoc-irreversible-badge')).toHaveTextContent(
        'Irreversible Action — Per-Booking Human Approval Required (Even in A2)'
      );

      // Verify Fits Calendar vs Calendar Conflict badges
      expect(
        screen.getByTestId('smart-slot-calendar-badge-slot-ped-101')
      ).toHaveTextContent('Fits Calendar');
      expect(
        screen.getByTestId('smart-slot-calendar-badge-slot-zocdoc-202')
      ).toHaveTextContent('Calendar Conflict');

      // Trigger Discover SMART Scheduling Slots
      fireEvent.change(screen.getByTestId('smart-slots-specialty-input'), {
        target: { value: 'pediatric_dentistry' },
      });
      fireEvent.submit(screen.getByTestId('discover-smart-slots-form'));

      await waitFor(() => {
        expect(onDiscoverSmartSlots).toHaveBeenCalledWith({
          specialty: 'pediatric_dentistry',
        });
      });

      // Trigger Request Booking Approval on Zocdoc slot
      fireEvent.click(
        screen.getByTestId('zocdoc-request-approval-btn-slot-zocdoc-202')
      );
      expect(onRequestZocdocApproval).toHaveBeenCalledWith({
        provider_id: 'prov-slot-zocdoc-202',
        provider_name: 'Dr. Marcus Vance, DDS',
        specialty: 'pediatric_dentistry',
        slot_id: 'slot-zocdoc-202',
        start_time: '2026-10-21T09:00:00Z',
      });

      // Verify staged Zocdoc preview card & payload hash
      expect(
        screen.getByTestId('zocdoc-booking-preview-card')
      ).toHaveTextContent('Dr. Marcus Vance, DDS');
      expect(screen.getByTestId('zocdoc-preview-hash')).toHaveTextContent(
        'Payload SHA-256: a3f5c8e1d9b04762819203847561928374650192837465019283746501928374'
      );
    });
  });

  describe('3. Expanded v2 EHR, Payer, Wearable & Android Health Connect Catalog (AU-73, AU-74, AU-75)', () => {
    it('renders Oracle Health, athenahealth, CMS Blue Button 2.0, Oura Ring, Google Health Connect, Microsoft Graph, and Android Health Connect Companion badge', () => {
      render(<CoordinatedV2Panel v2Connectors={SAMPLE_V2_CONNECTORS} />);

      expect(
        screen.getByTestId('android-health-connect-companion-badge')
      ).toHaveTextContent('Android Health Connect Companion');

      expect(
        screen.getByTestId('v2-connector-card-oracle_health_smart')
      ).toHaveTextContent('Oracle Health (SMART R4)');
      expect(
        screen.getByTestId('v2-connector-card-athenahealth_smart')
      ).toHaveTextContent('athenahealth (SMART R4)');
      expect(
        screen.getByTestId('v2-connector-card-cms_blue_button_2')
      ).toHaveTextContent('CMS Blue Button 2.0 (EOB Claims)');
      expect(
        screen.getByTestId('v2-connector-card-oura_ring_v2')
      ).toHaveTextContent('Oura Ring (Daily Sleep/HRV)');
      expect(
        screen.getByTestId('v2-connector-card-google_health_connect')
      ).toHaveTextContent('Google Health Connect');
      expect(
        screen.getByTestId('v2-connector-card-microsoft_graph_calendar')
      ).toHaveTextContent('Microsoft Graph Calendar');
    });
  });

  describe('4. Tamper-Evident Audit Hash Chain & OS Background Service Descriptors (AU-78 & AU-81)', () => {
    it('displays Chain Intact vs Tamper Detected states and renders launchctl, systemctl --user, and schtasks descriptors with 127.0.0.1 loopback notice', () => {
      const onVerifyAuditChain = vi.fn();

      const { rerender } = render(
        <CoordinatedV2Panel
          auditVerification={SAMPLE_AUDIT_INTACT}
          serviceDescriptors={SAMPLE_SERVICE_DESCRIPTORS}
          onVerifyAuditChain={onVerifyAuditChain}
        />
      );

      // Loopback bind notice
      expect(
        screen.getByTestId('os-service-loopback-notice')
      ).toHaveTextContent('127.0.0.1');

      // Audit chain intact state
      expect(screen.getByTestId('audit-chain-status-badge')).toHaveTextContent(
        'Chain Intact'
      );
      expect(screen.getByTestId('audit-chain-checked-count')).toHaveTextContent(
        'Checked events: 14'
      );
      expect(screen.getByTestId('audit-chain-head-hash')).toHaveTextContent(
        '7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069'
      );

      fireEvent.click(screen.getByTestId('verify-audit-chain-btn'));
      expect(onVerifyAuditChain).toHaveBeenCalledTimes(1);

      // OS service descriptors
      expect(
        screen.getByTestId('os-service-cmd-macos_launchd')
      ).toHaveTextContent('launchctl');
      expect(
        screen.getByTestId('os-service-cmd-linux_systemd')
      ).toHaveTextContent('systemctl --user');
      expect(
        screen.getByTestId('os-service-cmd-windows_task_scheduler')
      ).toHaveTextContent('schtasks');

      // Rerender with broken audit chain
      rerender(
        <CoordinatedV2Panel
          auditVerification={SAMPLE_AUDIT_BROKEN}
          serviceDescriptors={SAMPLE_SERVICE_DESCRIPTORS}
          onVerifyAuditChain={onVerifyAuditChain}
        />
      );
      expect(screen.getByTestId('audit-chain-status-badge')).toHaveTextContent(
        'Tamper Detected at Event evt-tampered-99'
      );
      expect(screen.getByTestId('audit-chain-broken-reason')).toHaveTextContent(
        'entry_hash mismatch on audit row evt-tampered-99'
      );
    });
  });

  describe('5. ConnectionsHub Coordinated v2 Tab Integration & Batch 7 API Client Helpers', () => {
    it('switches to Coordinated v2 tab in ConnectionsHub and invokes all Batch 7 API client endpoints', async () => {
      const sampleConnectors: ConnectorManifestSummary[] = [];
      const sampleConnections: ConnectionItem[] = [];

      render(
        <ConnectionsHub
          connectors={sampleConnectors}
          connections={sampleConnections}
          shcResult={SAMPLE_SHC_VERIFIED}
          smartSlots={SAMPLE_SMART_SLOTS}
          v2Connectors={SAMPLE_V2_CONNECTORS}
          auditVerification={SAMPLE_AUDIT_INTACT}
          serviceDescriptors={SAMPLE_SERVICE_DESCRIPTORS}
        />
      );

      fireEvent.click(screen.getByTestId('hub-tab-coordinated-v2'));
      expect(screen.getByTestId('coordinated-v2-panel')).toBeInTheDocument();
      expect(screen.getByTestId('shc-verification-badge')).toHaveTextContent(
        'ES256 Signature Verified'
      );

      const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
        ok: true,
        json: async () => ({}),
      } as Response);

      await verifySmartHealthCard('prof-1', {
        filename: 'card.smart-health-card',
        content: 'shc:/12345',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/imports/stage',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          body: JSON.stringify({
            format: 'smart_health_card',
            filename: 'card.smart-health-card',
            content: 'shc:/12345',
          }),
        })
      );

      await discoverSmartSchedulingSlots('prof-1', { specialty: 'pediatrics' });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/scheduling/smart-slots',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
          body: JSON.stringify({ specialty: 'pediatrics' }),
        })
      );

      await previewZocdocBooking('prof-1', {
        provider_id: 'prov-1',
        provider_name: 'Dr. Vance',
        specialty: 'dentistry',
        slot_id: 'slot-1',
        start_time: '2026-10-21T09:00:00Z',
      });
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/scheduling/zocdoc-preview',
        expect.objectContaining({
          method: 'POST',
          credentials: 'include',
        })
      );

      await verifyProfileAuditChain('prof-1');
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/profiles/prof-1/audit/verify',
        expect.objectContaining({ credentials: 'include' })
      );

      await fetchOsServiceDescriptors();
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/system/service-descriptors',
        expect.objectContaining({ credentials: 'include' })
      );

      await fetchV2ConnectorCatalog();
      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/v1/connectors/v2-catalog',
        expect.objectContaining({ credentials: 'include' })
      );
    });
  });
});
