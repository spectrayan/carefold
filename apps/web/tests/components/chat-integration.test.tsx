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
import {
  DEFAULT_USER_SETTINGS,
  saveSettings,
  CAREFOLD_SETTINGS_STORAGE_KEY
} from '@/lib/settings';

// Helper to construct synthetic SSE Response ReadableStreams
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

describe('ChatClient Integration (Suggestions, ThreadId, Model & Settings)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders ModelSelector and Settings trigger in header', () => {
    render(<ChatClient initialAgents={mockAgents} />);

    expect(screen.getByTestId('provider-selector')).toBeInTheDocument();
    expect(screen.getByTestId('model-selector')).toBeInTheDocument();
    expect(screen.getByTestId('open-settings-button')).toBeInTheDocument();
  });

  it('submits prompt with selected provider, model, and active threadId', async () => {
    let capturedBody: any = null;

    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat') {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Here is your checklist.' } },
            { event: 'done', data: { type: 'done', fullText: 'Here is your checklist.', threadId: 'thread-test-123' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });

    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Prepare visit questions' } });

    const sendBtn = screen.getByTitle('Send Prompt');
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });

    expect(capturedBody.agentId).toBe('visit-steward');
    expect(capturedBody.prompt).toBe('Prepare visit questions');
    expect(capturedBody.provider).toBe('ollama');
    expect(capturedBody.model).toBe('llama3.2');
    expect(capturedBody.threadId).toMatch(/^thread-/);
  });

  it('displays AI suggested next question chips and clicking one submits next prompt', async () => {
    let fetchCount = 0;
    const capturedBodies: any[] = [];

    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat') {
        fetchCount++;
        capturedBodies.push(JSON.parse(options.body));

        if (fetchCount === 1) {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'I prepared your notes.' } },
              {
                event: 'suggestions',
                data: {
                  type: 'suggestions',
                  suggestions: [
                    'What records should I bring?',
                    'How long will this appointment take?'
                  ]
                }
              },
              { event: 'done', data: { type: 'done', fullText: 'I prepared your notes.' } }
            ])
          );
        } else {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Bring your past lab results.' } },
              { event: 'done', data: { type: 'done', fullText: 'Bring your past lab results.' } }
            ])
          );
        }
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });

    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    // 1. Send first prompt
    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'First question' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    // 2. Wait for assistant text and suggestions chips
    await waitFor(() => {
      expect(screen.getByText('I prepared your notes.')).toBeInTheDocument();
      expect(screen.getByTestId('suggested-questions-container')).toBeInTheDocument();
    });

    expect(screen.getByText('What records should I bring?')).toBeInTheDocument();

    // 3. Click suggestion chip
    fireEvent.click(screen.getByText('What records should I bring?'));

    // 4. Verify second request was dispatched with suggested question and same threadId
    await waitFor(() => {
      expect(fetchCount).toBe(2);
    });

    expect(capturedBodies[1].prompt).toBe('What records should I bring?');
    expect(capturedBodies[1].threadId).toBe(capturedBodies[0].threadId);

    // Suggestions container clears while streaming next turn
    expect(screen.queryByText('How long will this appointment take?')).not.toBeInTheDocument();
  });

  it('clicking New Session resets conversation and generates fresh threadId', async () => {
    let capturedThreadIds: string[] = [];

    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat') {
        const body = JSON.parse(options.body);
        capturedThreadIds.push(body.threadId);
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Reply' } },
            { event: 'done', data: { type: 'done', fullText: 'Reply' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });

    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    // Send first message
    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Session 1 message' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByText('Reply')).toBeInTheDocument();
    });

    // Click "New Session"
    const newSessionBtn = screen.getByTitle('Start a new chat session');
    fireEvent.click(newSessionBtn);

    // Message list is reset
    expect(screen.queryByText('Session 1 message')).not.toBeInTheDocument();

    // Send message in new session
    fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Session 2 message' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(capturedThreadIds).toHaveLength(2);
    });

    // Distinct thread IDs
    expect(capturedThreadIds[0]).not.toBe(capturedThreadIds[1]);
  });

  it('renders EmergencyEscalationCard upon emergency refusal event and keeps composer usable', async () => {
    const mockFetch = vi.fn().mockImplementation((url, _options) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            {
              event: 'refusal',
              data: {
                type: 'refusal',
                reason: 'emergency_red_flag:crushing_chest_pain',
                message: 'EMERGENCY WARNING: Acute crushing chest pain detected. Call 911 immediately.',
                category: 'crushing_chest_pain'
              }
            },
            {
              event: 'done',
              data: {
                type: 'done',
                fullText: 'Carefold AI agents provide educational navigation only.',
                refused: true,
                refusalReason: 'emergency_red_flag:crushing_chest_pain',
                threadId: 'thread-emerg-123'
              }
            }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });

    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'I have crushing chest pain and shortness of breath' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByTestId('emergency-escalation-card')).toBeInTheDocument();
    });

    // Verify verbatim acute referral message is preserved (not overwritten by fullText)
    expect(screen.getByTestId('emergency-backend-message')).toHaveTextContent(
      'EMERGENCY WARNING: Acute crushing chest pain detected. Call 911 immediately.'
    );

    // Verify action links
    expect(screen.getByTestId('emergency-call-911-btn')).toHaveAttribute('href', 'tel:911');
    expect(screen.getByTestId('emergency-find-er-btn')).toHaveAttribute('href', expect.stringContaining('maps'));

    // Verify composer remains enabled and usable (not locked)
    expect(input).not.toBeDisabled();
    fireEvent.change(input, { target: { value: 'Follow up question' } });
    expect(screen.getByTitle('Send Prompt')).not.toBeDisabled();
  });

  it('renders on-device privacy claim in empty state when local provider is active', () => {
    render(<ChatClient initialAgents={mockAgents} />);

    const emptyPrivacyText = screen.getByTestId('chat-empty-state-privacy');
    expect(emptyPrivacyText).toBeInTheDocument();
    expect(emptyPrivacyText).toHaveTextContent(
      'Ask questions or drop relevant documents into the chat. All data remains exclusively on your device.'
    );
  });

  it('suppresses on-device privacy claim when cloud provider is selected', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'openai',
        model: 'gpt-4o'
      })
    );

    render(<ChatClient initialAgents={mockAgents} />);

    const emptyPrivacyText = screen.getByTestId('chat-empty-state-privacy');
    expect(emptyPrivacyText).toHaveTextContent(
      'Ask questions or drop relevant documents into the chat. Your messages are sent to OpenAI to generate replies.'
    );
    expect(emptyPrivacyText).not.toHaveTextContent('All data remains exclusively on your device');
  });

  it('suppresses on-device privacy claim when remote LAN Ollama is configured', () => {
    localStorage.setItem(
      CAREFOLD_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        ...DEFAULT_USER_SETTINGS,
        provider: 'ollama',
        endpoints: {
          ...DEFAULT_USER_SETTINGS.endpoints,
          ollamaUrl: 'http://192.168.1.100:11434'
        }
      })
    );

    render(<ChatClient initialAgents={mockAgents} />);

    const emptyPrivacyText = screen.getByTestId('chat-empty-state-privacy');
    expect(emptyPrivacyText).toHaveTextContent(
      'Ask questions or drop relevant documents into the chat. Your messages are sent to Ollama to generate replies.'
    );
    expect(emptyPrivacyText).not.toHaveTextContent('All data remains exclusively on your device');
  });

  it('reactively updates empty state privacy copy when provider changes', async () => {
    render(<ChatClient initialAgents={mockAgents} />);

    const emptyPrivacyText = screen.getByTestId('chat-empty-state-privacy');
    expect(emptyPrivacyText).toHaveTextContent('All data remains exclusively on your device.');

    // Switch to Claude
    saveSettings({
      provider: 'anthropic',
      model: 'claude-3-5-sonnet-latest'
    });

    await waitFor(() => {
      expect(emptyPrivacyText).toHaveTextContent(
        'Ask questions or drop relevant documents into the chat. Your messages are sent to Claude to generate replies.'
      );
    });
    expect(emptyPrivacyText).not.toHaveTextContent('All data remains exclusively on your device');
  });

  it('renders agent selector with accessible label, aria-describedby, and plain-language risk labels', () => {
    const customAgents: AgentSummary[] = [
      {
        id: 'cardiology-guide',
        title: 'Cardiology Guide',
        version: '0.1.0',
        risk_class: 'clinical_assist',
        skills: ['cardiology-prep'],
        effectiveTools: ['skill-docs'],
        starters: []
      },
      {
        id: 'benefits-guide',
        title: 'Benefits Guide',
        version: '0.1.0',
        risk_class: 'admin',
        skills: ['benefits-explainer'],
        effectiveTools: ['attach-read'],
        starters: []
      },
      {
        id: 'visit-steward',
        title: 'Visit Steward',
        version: '0.1.0',
        risk_class: 'wellness',
        skills: ['visit-prep'],
        effectiveTools: ['skill-docs'],
        starters: []
      }
    ];

    render(<ChatClient initialAgents={customAgents} />);

    // Combobox accessible name and attributes
    const selector = screen.getByRole('combobox', { name: /select health agent/i });
    expect(selector).toBeInTheDocument();
    expect(selector).toHaveAttribute('id', 'agent-selector');
    expect(selector).toHaveAttribute('aria-describedby', 'agent-selector-description');

    const desc = document.getElementById('agent-selector-description');
    expect(desc).toBeInTheDocument();

    // Verify option text has plain labels without raw snake_case tokens
    const options = screen.getAllByRole('option');
    expect(options[0]).toHaveTextContent('Cardiology Guide (Clinical assist)');
    expect(options[0]).not.toHaveTextContent('clinical_assist');

    expect(options[1]).toHaveTextContent('Benefits Guide (Admin)');
    expect(options[1]).not.toHaveTextContent('(admin)');

    expect(options[2]).toHaveTextContent('Visit Steward (Wellness)');
    expect(options[2]).not.toHaveTextContent('(wellness)');
  });

  // ---------------------------------------------------------------------------
  // Screen Reader Live Region Announcements & Anti-Thrashing (Issue #90)
  // ---------------------------------------------------------------------------

  it('renders persistent polite and assertive screen reader live regions and message log container', () => {
    render(<ChatClient initialAgents={mockAgents} />);

    // Polite live region
    const politeAnnouncer = screen.getByTestId('chat-live-announcer-polite');
    expect(politeAnnouncer).toBeInTheDocument();
    expect(politeAnnouncer).toHaveAttribute('role', 'status');
    expect(politeAnnouncer).toHaveAttribute('aria-live', 'polite');
    expect(politeAnnouncer).toHaveAttribute('aria-atomic', 'true');
    expect(politeAnnouncer.className).toContain('sr-only');

    // Assertive live region
    const assertiveAnnouncer = screen.getByTestId('chat-live-announcer-assertive');
    expect(assertiveAnnouncer).toBeInTheDocument();
    expect(assertiveAnnouncer).toHaveAttribute('role', 'alert');
    expect(assertiveAnnouncer).toHaveAttribute('aria-live', 'assertive');
    expect(assertiveAnnouncer).toHaveAttribute('aria-atomic', 'true');
    expect(assertiveAnnouncer.className).toContain('sr-only');

    // Message log container
    const messageLog = screen.getByRole('log', { name: /chat history with visit steward/i });
    expect(messageLog).toBeInTheDocument();
    expect(messageLog).toHaveAttribute('aria-live', 'off');
  });

  it('announces generation start status politely when stream begins', async () => {
    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Hello' } },
            { event: 'done', data: { type: 'done', fullText: 'Hello' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Schedule checkup' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    // Immediately on submission, polite announcer is populated with status
    const politeAnnouncer = screen.getByTestId('chat-live-announcer-polite');
    expect(politeAnnouncer).toHaveTextContent('Thinking... Generating response from Visit Steward.');
  });

  it('prevents screen reader thrashing by keeping announcer silent during token stream', async () => {
    let streamController: ReadableStreamDefaultController | null = null;
    const stream = new ReadableStream({
      start(controller) {
        streamController = controller;
      }
    });

    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' }
          })
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Tell me more' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    const politeAnnouncer = screen.getByTestId('chat-live-announcer-polite');
    expect(politeAnnouncer).toHaveTextContent('Thinking... Generating response from Visit Steward.');

    // Push individual token chunks
    const encoder = new TextEncoder();
    streamController!.enqueue(encoder.encode('event: token\ndata: {"type":"token","delta":"Token 1 "}\n\n'));
    streamController!.enqueue(encoder.encode('event: token\ndata: {"type":"token","delta":"Token 2 "}\n\n'));

    // Announcer text must NOT contain raw streaming tokens (anti-thrashing guarantee)
    expect(politeAnnouncer).not.toHaveTextContent('Token 1');
    expect(politeAnnouncer).not.toHaveTextContent('Token 2');
    expect(politeAnnouncer).toHaveTextContent('Thinking... Generating response from Visit Steward.');

    // Close stream
    streamController!.enqueue(encoder.encode('event: done\ndata: {"type":"done","fullText":"Token 1 Token 2"}\n\n'));
    streamController!.close();

    // Once stream completes, full text is announced with attribution
    await waitFor(() => {
      expect(politeAnnouncer).toHaveTextContent('Response from Visit Steward: Token 1 Token 2');
    });
  });

  it('announces completed assistant response once upon done event with agent attribution', async () => {
    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Your visit notes are ready.' } },
            { event: 'done', data: { type: 'done', fullText: 'Your visit notes are ready.' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Prepare summary' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByTestId('chat-live-announcer-polite')).toHaveTextContent(
        'Response from Visit Steward: Your visit notes are ready.'
      );
    });
  });

  it('announces emergency refusal assertively in alert live region', async () => {
    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            {
              event: 'refusal',
              data: {
                type: 'refusal',
                reason: 'emergency_red_flag:acute_stroke',
                message: 'EMERGENCY WARNING: Acute stroke symptoms detected. Call 911 immediately.',
                category: 'acute_stroke'
              }
            },
            {
              event: 'done',
              data: {
                type: 'done',
                fullText: 'Educational navigation only.',
                refused: true,
                refusalReason: 'emergency_red_flag:acute_stroke'
              }
            }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Sudden facial droop and arm weakness' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByTestId('chat-live-announcer-assertive')).toHaveTextContent(
        'Emergency Alert: EMERGENCY WARNING: Acute stroke symptoms detected. Call 911 immediately.'
      );
    });
  });

  it('announces runtime errors assertively with role="alert"', async () => {
    const mockFetch = vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'error', data: { type: 'error', message: 'Ollama is unreachable.' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const input = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(input, { target: { value: 'Ping model' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByTestId('chat-live-announcer-assertive')).toHaveTextContent(
        'Error: Ollama is unreachable.'
      );
    });

    const errorBanner = screen.getByTestId('chat-error-banner');
    expect(errorBanner).toHaveAttribute('role', 'alert');
    expect(errorBanner).toHaveAttribute('aria-live', 'assertive');
  });
});



