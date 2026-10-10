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

describe('ChatClient Composer (Auto-Expanding Textarea & Mobile Ergonomics)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn());
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders a textarea with auto-expand classes and 16px mobile font to prevent iOS zoom', () => {
    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    expect(textarea.tagName.toLowerCase()).toBe('textarea');
    expect(textarea).toHaveAttribute('rows', '1');

    // Verify iOS Safari zoom prevention class (text-base on mobile <640px, sm:text-sm on desktop)
    expect(textarea.className).toContain('text-base');
    expect(textarea.className).toContain('sm:text-sm');

    // Verify bounds and resize prevention
    expect(textarea.className).toContain('min-h-[44px]');
    expect(textarea.className).toContain('max-h-[160px]');
    expect(textarea.className).toContain('resize-none');

    // Verify submit button touch target accessibility (min 44px x 44px)
    const submitBtn = screen.getByTitle('Send Prompt');
    expect(submitBtn.className).toContain('min-w-[44px]');
    expect(submitBtn.className).toContain('min-h-[44px]');
  });

  it('submits on Enter without Shift and calls API', async () => {
    let capturedBody: any = null;
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat' || url === '/api/v1/chat') {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Answer' } },
            { event: 'done', data: { type: 'done', fullText: 'Answer' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(textarea, { target: { value: 'My medical question' } });

    // Press Enter without shift
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });
    expect(capturedBody.prompt).toBe('My medical question');
  });

  it('does NOT submit on Shift + Enter (allows multi-line insertion)', () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(textarea, { target: { value: 'First line' } });

    // Press Shift + Enter
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: true });

    // Ensure chat API was not triggered
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
    // Input remains unchanged
    expect(textarea).toHaveValue('First line');
  });

  it('ignores Enter key during CJK / IME composition', () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(textarea, { target: { value: 'にほんご' } });

    // Simulate IME composition enter
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: true,
      nativeEvent: { isComposing: true }
    });

    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('does NOT submit on plain Enter when text is purely whitespace and no files attached', () => {
    const mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(textarea, { target: { value: '   ' } });

    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('dynamically resizes height up to 160px and resets to 42px on submission', async () => {
    const mockFetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Done' } },
          { event: 'done', data: { type: 'done', fullText: 'Done' } }
        ])
      )
    );
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i) as HTMLTextAreaElement;

    // Simulate expanding scrollHeight
    Object.defineProperty(textarea, 'scrollHeight', {
      configurable: true,
      value: 120
    });

    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3' } });
    expect(textarea.style.height).toBe('120px');

    // Simulate exceeding max height
    Object.defineProperty(textarea, 'scrollHeight', {
      configurable: true,
      value: 250
    });
    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6' } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');

    // Submit prompt
    fireEvent.click(screen.getByTitle('Send Prompt'));

    // Should reset height back to 42px
    await waitFor(() => {
      expect(textarea.style.height).toBe('42px');
      expect(textarea.style.overflowY).toBe('hidden');
    });
  });

  it('disables textarea and renders Stop Generation button during streaming', async () => {
    let resolveStream: () => void = () => {};
    const streamPromise = new Promise<void>((res) => {
      resolveStream = res;
    });

    const mockFetch = vi.fn().mockImplementation(() => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        async start(controller) {
          controller.enqueue(encoder.encode('event: token\ndata: {"type":"token","delta":"Hi"}\n\n'));
          await streamPromise;
          controller.enqueue(encoder.encode('event: done\ndata: {"type":"done","fullText":"Hi"}\n\n'));
          controller.close();
        }
      });
      return Promise.resolve(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    const textarea = screen.getByPlaceholderText(/Message/i);
    fireEvent.change(textarea, { target: { value: 'Streaming test' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    // During streaming, textarea is disabled
    await waitFor(() => {
      expect(textarea).toBeDisabled();
      expect(screen.getByTitle('Stop Generation')).toBeInTheDocument();
    });

    // Resolve stream
    resolveStream();

    await waitFor(() => {
      expect(textarea).not.toBeDisabled();
      expect(screen.getByTitle('Send Prompt')).toBeInTheDocument();
    });
  });
});
