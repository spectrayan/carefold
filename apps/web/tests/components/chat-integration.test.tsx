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
});
