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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';
import { mapChatErrorToFriendlyNotice } from '@/lib/chatErrorMapper';

vi.mock('@/components/ThemeScript', () => ({
  ThemeScript: () => null
}));

// Helper to construct SSE stream
function createMockSSEResponse(events: Array<{ event?: string; data: Record<string, any> }>) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const ev of events) {
        const eventLine = ev.event ? `event: ${ev.event}\n` : '';
        const dataLine = `data: ${JSON.stringify(ev.data)}\n\n`;
        controller.enqueue(encoder.encode(eventLine + dataLine));
      }
      controller.close();
    }
  });

  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' }
  });
}

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    risk_class: 'wellness',
    skills: ['visit-prep'],
    effectiveTools: ['skill-docs'],
    starters: ['What should I ask my doctor?']
  }
];

describe('Error Recovery Suite (Issue #176)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
  });

  // ---------------------------------------------------------------------------
  // 1. Error Mapper Unit Invariants
  // ---------------------------------------------------------------------------
  describe('chatErrorMapper Invariants', () => {
    it('maps network & connection refusal errors to MODEL_UNREACHABLE with retry enabled', () => {
      const notice = mapChatErrorToFriendlyNotice(new Error('connect ECONNREFUSED 127.0.0.1:11434'), 'test prompt');
      expect(notice.code).toBe('MODEL_UNREACHABLE');
      expect(notice.userMessage).toContain('Cannot connect to the model service');
      expect(notice.canRetry).toBe(true);
      expect(notice.failedPrompt).toBe('test prompt');
      expect(notice.technicalDetails).toContain('ECONNREFUSED');
    });

    it('maps JSONDecodeError & 500 server errors to INVALID_RESPONSE with retry enabled', () => {
      const notice = mapChatErrorToFriendlyNotice(new Error('JSONDecodeError: Expecting value: line 1 column 1 (char 0)'), 'prompt 123');
      expect(notice.code).toBe('INVALID_RESPONSE');
      expect(notice.userMessage).toContain('Something went wrong while generating an answer');
      expect(notice.canRetry).toBe(true);
      expect(notice.failedPrompt).toBe('prompt 123');
      expect(notice.technicalDetails).toContain('JSONDecodeError');
    });

    it('maps 401 unauthorized to UNAUTHORIZED with retry disabled', () => {
      const notice = mapChatErrorToFriendlyNotice(new Error('HTTP 401: Unauthorized API key'), 'secret prompt');
      expect(notice.code).toBe('UNAUTHORIZED');
      expect(notice.userMessage).toContain('An API key or active sign-in is required');
      expect(notice.canRetry).toBe(false);
      expect(notice.failedPrompt).toBe('secret prompt');
    });

    it('maps 504 timeouts to TIMEOUT with retry enabled', () => {
      const notice = mapChatErrorToFriendlyNotice(new Error('Gateway Timeout 504'), 'timed out prompt');
      expect(notice.code).toBe('TIMEOUT');
      expect(notice.userMessage).toContain('The model took too long');
      expect(notice.canRetry).toBe(true);
    });
  });

  // ---------------------------------------------------------------------------
  // 2. Simulated Failed SSE Streaming
  // ---------------------------------------------------------------------------
  describe('Simulated Failed SSE Streaming & UI Recovery', () => {
    it('renders friendly error banner with details disclosure and retry button on SSE error event', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'error', data: { type: 'error', message: 'LangGraph workflow halted unexpectedly' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Prepare my dossier' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('chat-error-banner')).toBeInTheDocument();
      });

      const banner = screen.getByTestId('chat-error-banner');
      expect(banner).toHaveAttribute('role', 'alert');
      expect(banner).toHaveAttribute('aria-live', 'assertive');

      // Verify friendly message
      expect(banner).toHaveTextContent(/An unexpected issue occurred while chatting|Something went wrong/);

      // Verify details disclosure
      const details = banner.querySelector('details');
      expect(details).toBeInTheDocument();
      expect(details).toHaveTextContent('Technical details');
      expect(details).toHaveTextContent('LangGraph workflow halted unexpectedly');

      // Verify retry button is active
      const retryBtn = screen.getByTestId('chat-retry-turn-btn');
      expect(retryBtn).toBeInTheDocument();
      expect(retryBtn).toHaveTextContent('Try again');
    });
  });

  // ---------------------------------------------------------------------------
  // 3. Simulated Network Fetch Error & Successful Retry Flow
  // ---------------------------------------------------------------------------
  describe('Simulated Network Error & Active Retry Execution', () => {
    it('handles network rejection, renders retry trigger, and successfully recovers turn on retry click', async () => {
      let fetchAttempts = 0;
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          fetchAttempts++;
          if (fetchAttempts === 1) {
            // First attempt: network failure
            return Promise.reject(new Error('Failed to fetch'));
          }
          // Second attempt (retry): successful stream
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Recovered answer successfully!' } },
              { event: 'done', data: { type: 'done', fullText: 'Recovered answer successfully!' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Query during outage' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Verify error banner appears
      await waitFor(() => {
        expect(screen.getByTestId('chat-error-banner')).toBeInTheDocument();
      });

      expect(screen.getByTestId('chat-error-banner')).toHaveTextContent(/Cannot connect to the model service/);
      const retryBtn = screen.getByTestId('chat-retry-turn-btn');
      expect(retryBtn).toBeInTheDocument();

      // Click retry
      fireEvent.click(retryBtn);

      // Verify banner dismissed and turn retried
      await waitFor(() => {
        expect(screen.queryByTestId('chat-error-banner')).not.toBeInTheDocument();
      });

      expect(fetchAttempts).toBe(2);

      // Verify recovered message appears in chat
      await waitFor(() => {
        expect(screen.getByText('Recovered answer successfully!')).toBeInTheDocument();
      });
    });
  });

  // ---------------------------------------------------------------------------
  // 4. Simulated Raw JSONDecodeError Response
  // ---------------------------------------------------------------------------
  describe('Simulated Raw JSONDecodeError Response', () => {
    it('catches JSON error payload with JSONDecodeError and maps to friendly recovery notice', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            new Response(JSON.stringify({ error: 'JSONDecodeError: Expecting value: line 1 column 1 (char 0)' }), {
              status: 500,
              statusText: 'Internal Server Error',
              headers: { 'Content-Type': 'application/json' }
            })
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Broken JSON query' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('chat-error-banner')).toBeInTheDocument();
      });

      const banner = screen.getByTestId('chat-error-banner');
      expect(banner).toHaveTextContent('Something went wrong while generating an answer. Your message was saved.');
      expect(screen.getByTestId('chat-retry-turn-btn')).toBeInTheDocument();

      const details = banner.querySelector('details');
      expect(details).toHaveTextContent('JSONDecodeError');
    });

    it('catches non-JSON HTTP 500 response and maps to friendly recovery notice', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            new Response('Internal Server Error', {
              status: 500,
              statusText: 'Internal Server Error',
              headers: { 'Content-Type': 'text/plain' }
            })
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Server crash query' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('chat-error-banner')).toBeInTheDocument();
      });

      const banner = screen.getByTestId('chat-error-banner');
      expect(banner).toHaveTextContent('Something went wrong while generating an answer. Your message was saved.');
      expect(screen.getByTestId('chat-retry-turn-btn')).toBeInTheDocument();
      expect(banner.querySelector('details')).toHaveTextContent('HTTP error 500');
    });
  });

  // ---------------------------------------------------------------------------
  // 5. Non-Retryable Error (401 Unauthorized)
  // ---------------------------------------------------------------------------
  describe('Non-Retryable Auth Error', () => {
    it('suppresses retry button and displays Settings action on 401 Unauthorized', async () => {
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            new Response('Unauthorized: missing_api_key', {
              status: 401,
              statusText: 'Unauthorized'
            })
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Unauthenticated prompt' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByTestId('chat-error-banner')).toBeInTheDocument();
      });

      const banner = screen.getByTestId('chat-error-banner');
      expect(banner).toHaveTextContent('An API key or active sign-in is required to talk to this helper.');

      // Retry button MUST NOT be present
      expect(screen.queryByTestId('chat-retry-turn-btn')).not.toBeInTheDocument();

      // Settings button MUST be present
      const settingsBtn = screen.getByTestId('chat-open-diagnostics-btn');
      expect(settingsBtn).toBeInTheDocument();
      expect(settingsBtn).toHaveTextContent('Settings');
    });
  });
});
