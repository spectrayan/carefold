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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import React from 'react';
import { ChatClient } from '@/app/chat/ChatClient';
import { ClinicalConsentDialog } from '@/components/ClinicalConsentDialog';
import { SettingsModal } from '@/components/SettingsModal';
import {
  CLINICAL_CONSENT_STORAGE_KEY,
  grantClinicalConsent,
  hasClinicalConsent,
  withdrawClinicalConsent
} from '@/lib/clinicalConsent';
import { DEFAULT_USER_SETTINGS } from '@/lib/settings';
import type { AgentSummary } from '@/lib/types';

function sseResponse(text: string) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(`event: token\ndata: ${JSON.stringify({ type: 'token', delta: text })}\n\n`));
      controller.enqueue(encoder.encode(`event: done\ndata: ${JSON.stringify({ type: 'done', fullText: text })}\n\n`));
      controller.close();
    }
  });
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

const clinicalAgent: AgentSummary = {
  id: 'cardiology-guide',
  title: 'Cardiology Guide',
  version: '0.1.0',
  risk_class: 'clinical_assist',
  skills: ['cardiology-prep'],
  effectiveTools: ['skill-docs'],
  starters: ['Help me prepare for my cardiology visit'],
  description: 'Helps you prepare for heart health appointments.',
  forbidden: ['diagnose', 'prescribe', 'dose', 'replace_emergency_care', 'instruct_stop_medication']
};

const wellnessAgent: AgentSummary = {
  id: 'habit-companion',
  title: 'Habit Companion',
  version: '0.1.0',
  risk_class: 'wellness',
  skills: ['habit-checkin'],
  effectiveTools: ['workspace-note'],
  starters: ['Check in on my habits']
};

function setupFetch() {
  const chatBodies: any[] = [];
  const urls: string[] = [];
  const mockFetch = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
    urls.push(String(url));
    if (url === '/api/chat' || url === '/api/v1/chat') {
      chatBodies.push(JSON.parse(String(options?.body)));
      return Promise.resolve(sseResponse('Here is your checklist.'));
    }
    return Promise.resolve(new Response('{}', { status: 200 }));
  });
  vi.stubGlobal('fetch', mockFetch);
  return { chatBodies, urls, mockFetch };
}

function typeAndSend(text: string) {
  fireEvent.change(screen.getByTestId('chat-composer-textarea'), { target: { value: text } });
  fireEvent.click(screen.getByTitle('Send Prompt'));
}

describe('Clinical consent gate (#87)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe('ChatClient', () => {
    it('shows the consent dialog for a clinical_assist agent without stored consent', async () => {
      setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);

      const dialog = await screen.findByTestId('clinical-consent-dialog');
      expect(dialog).toHaveAttribute('role', 'dialog');
      expect(dialog).toHaveAttribute('aria-modal', 'true');
      expect(screen.getByText('Before you chat with Cardiology Guide')).toBeInTheDocument();

      // Forbidden list rendered in plain language and emergency guidance shown
      const forbidden = screen.getByTestId('clinical-consent-forbidden-list');
      expect(forbidden).toHaveTextContent('Diagnose a condition');
      expect(forbidden).toHaveTextContent('stop, skip, or pause a medication');
      expect(screen.getByTestId('clinical-consent-emergency')).toHaveTextContent('911');
      expect(screen.getByTestId('clinical-consent-emergency')).toHaveTextContent('988');

      // Composer is disabled while gated
      expect(screen.getByTestId('chat-composer-textarea')).toBeDisabled();
      expect(screen.queryByTestId('clinical-consent-chip')).not.toBeInTheDocument();
    });

    it('requires the acknowledgement checkbox before consent can be granted', async () => {
      setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);

      const accept = await screen.findByTestId('clinical-consent-accept');
      expect(accept).toBeDisabled();
      fireEvent.click(accept);
      expect(hasClinicalConsent('cardiology-guide')).toBe(false);

      fireEvent.click(screen.getByTestId('clinical-consent-ack'));
      expect(accept).not.toBeDisabled();
    });

    it('grant: stores consent, shows the header chip, and sends allow_clinical=true', async () => {
      const { chatBodies } = setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);

      fireEvent.click(await screen.findByTestId('clinical-consent-ack'));
      fireEvent.click(screen.getByTestId('clinical-consent-accept'));

      await waitFor(() => expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument());
      expect(hasClinicalConsent('cardiology-guide')).toBe(true);
      expect(screen.getByTestId('clinical-consent-chip')).toHaveTextContent('Clinical assist: consent given');

      const stored = JSON.parse(localStorage.getItem(CLINICAL_CONSENT_STORAGE_KEY) || '{}');
      expect(Date.parse(stored['cardiology-guide'].grantedAt)).not.toBeNaN();

      typeAndSend('Prepare my questions');
      await waitFor(() => expect(chatBodies).toHaveLength(1));
      expect(chatBodies[0].allow_clinical).toBe(true);
      expect(chatBodies[0].allowClinical).toBe(true);
    });

    it('decline: closes the dialog, explains the gate, and never calls /api/chat', async () => {
      const { mockFetch } = setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);

      fireEvent.click(await screen.findByTestId('clinical-consent-decline'));

      await waitFor(() => expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument());
      expect(screen.getByTestId('clinical-consent-gate')).toHaveTextContent('turned off until you give consent');
      expect(screen.getByTestId('chat-composer-textarea')).toBeDisabled();
      expect(screen.getByTitle('Send Prompt')).toBeDisabled();
      expect(hasClinicalConsent('cardiology-guide')).toBe(false);

      // Starter chips must not bypass the gate; they re-open the dialog instead
      fireEvent.click(screen.getByText('Help me prepare for my cardiology visit'));
      expect(await screen.findByTestId('clinical-consent-dialog')).toBeInTheDocument();
      expect(mockFetch.mock.calls.some(([url]) => url === '/api/chat' || url === '/api/v1/chat')).toBe(false);
    });

    it('Escape declines instead of granting consent', async () => {
      setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);
      await screen.findByTestId('clinical-consent-dialog');

      fireEvent.keyDown(window, { key: 'Escape' });

      await waitFor(() => expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument());
      expect(hasClinicalConsent('cardiology-guide')).toBe(false);
      expect(screen.getByTestId('clinical-consent-gate')).toBeInTheDocument();
    });

    it('"Review and give consent" re-opens the dialog after declining', async () => {
      setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);
      fireEvent.click(await screen.findByTestId('clinical-consent-decline'));

      fireEvent.click(await screen.findByTestId('clinical-consent-review'));
      expect(await screen.findByTestId('clinical-consent-dialog')).toBeInTheDocument();
    });

    it('wellness agents are not gated and send allow_clinical=false', async () => {
      const { chatBodies } = setupFetch();
      render(<ChatClient initialAgents={[wellnessAgent]} />);

      await waitFor(() => expect(screen.getByTestId('chat-composer-textarea')).not.toBeDisabled());
      expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument();
      expect(screen.queryByTestId('clinical-consent-chip')).not.toBeInTheDocument();

      typeAndSend('How did I do this week?');
      await waitFor(() => expect(chatBodies).toHaveLength(1));
      expect(chatBodies[0].allow_clinical).toBe(false);
    });

    it('withdraw: takes effect on the next request without reload', async () => {
      grantClinicalConsent('cardiology-guide');
      const { chatBodies, mockFetch } = setupFetch();
      render(<ChatClient initialAgents={[clinicalAgent]} />);

      expect(await screen.findByTestId('clinical-consent-chip')).toBeInTheDocument();
      expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument();

      typeAndSend('First question');
      await waitFor(() => expect(chatBodies).toHaveLength(1));
      expect(chatBodies[0].allow_clinical).toBe(true);
      await waitFor(() => expect(screen.getByTestId('chat-composer-textarea')).not.toBeDisabled());

      act(() => withdrawClinicalConsent('cardiology-guide'));

      await waitFor(() => expect(screen.queryByTestId('clinical-consent-chip')).not.toBeInTheDocument());
      expect(await screen.findByTestId('clinical-consent-dialog')).toBeInTheDocument();
      expect(screen.getByTestId('chat-composer-textarea')).toBeDisabled();

      const chatCalls = mockFetch.mock.calls.filter(([url]) => url === '/api/chat' || url === '/api/v1/chat').length;
      expect(chatCalls).toBe(1);
    });

    it('does not probe the gated detail endpoint for starters without consent', async () => {
      const { urls } = setupFetch();
      render(<ChatClient initialAgents={[{ ...clinicalAgent, starters: [] }]} />);
      await screen.findByTestId('clinical-consent-dialog');
      expect(urls.some((u) => u.includes('allow_clinical=true'))).toBe(false);
    });
  });

  describe('ClinicalConsentDialog', () => {
    it('falls back to the default forbidden list when the agent provides none', () => {
      render(
        <ClinicalConsentDialog
          isOpen
          agent={{ id: 'x-guide', title: 'X Guide' }}
          onAccept={vi.fn()}
          onDecline={vi.fn()}
        />
      );
      const items = screen.getByTestId('clinical-consent-forbidden-list').querySelectorAll('li');
      expect(items.length).toBe(5);
    });

    it('renders nothing when closed', () => {
      render(
        <ClinicalConsentDialog isOpen={false} agent={{ id: 'x', title: 'X' }} onAccept={vi.fn()} onDecline={vi.fn()} />
      );
      expect(screen.queryByTestId('clinical-consent-dialog')).not.toBeInTheDocument();
    });
  });

  describe('SettingsModal consent section', () => {
    it('shows an empty state when no consent is stored', () => {
      render(<SettingsModal isOpen onClose={vi.fn()} initialSettings={DEFAULT_USER_SETTINGS} />);
      expect(screen.getByTestId('clinical-consent-empty')).toBeInTheDocument();
    });

    it('lists consents with agent titles and withdraws them individually or all at once', async () => {
      grantClinicalConsent('cardiology-guide');
      grantClinicalConsent('neurology-guide');

      render(
        <SettingsModal
          isOpen
          onClose={vi.fn()}
          initialSettings={DEFAULT_USER_SETTINGS}
          agents={[{ id: 'cardiology-guide', title: 'Cardiology Guide' }]}
        />
      );

      const cardio = await screen.findByTestId('clinical-consent-entry-cardiology-guide');
      expect(cardio).toHaveTextContent('Cardiology Guide');
      expect(cardio).toHaveTextContent('Consent given');
      // Falls back to the id when no title is known
      expect(screen.getByTestId('clinical-consent-entry-neurology-guide')).toHaveTextContent('neurology-guide');

      fireEvent.click(screen.getByTestId('withdraw-clinical-consent-cardiology-guide'));
      await waitFor(() =>
        expect(screen.queryByTestId('clinical-consent-entry-cardiology-guide')).not.toBeInTheDocument()
      );
      expect(hasClinicalConsent('cardiology-guide')).toBe(false);
      expect(hasClinicalConsent('neurology-guide')).toBe(true);

      act(() => {
        grantClinicalConsent('derma-guide');
      });
      fireEvent.click(await screen.findByTestId('withdraw-all-clinical-consent'));
      await waitFor(() => expect(screen.getByTestId('clinical-consent-empty')).toBeInTheDocument());
      expect(hasClinicalConsent('neurology-guide')).toBe(false);
      expect(hasClinicalConsent('derma-guide')).toBe(false);
    });
  });
});
