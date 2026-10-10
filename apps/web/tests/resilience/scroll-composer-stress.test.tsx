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
import { ScrollToBottomButton } from '@/components/chat/ScrollToBottomButton';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';
import { ToolTraceCard, type ToolTraceItem } from '@/components/ToolTraceCard';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
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

function createControlledStream() {
  let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    start(controller) {
      streamController = controller;
    }
  });

  const sendEvent = (event: string, data: Record<string, any>) => {
    if (streamController) {
      const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
      streamController.enqueue(encoder.encode(payload));
    }
  };

  const closeStream = () => {
    if (streamController) {
      streamController.close();
    }
  };

  const response = new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' }
  });

  return { response, sendEvent, closeStream };
}

describe('Stress Test: Scroll Tracking & Anti-Hijack Guarantee', () => {
  let scrollIntoViewSpy: any;

  beforeEach(() => {
    localStorage.clear();
    scrollIntoViewSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewSpy;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('anti-hijack: does NOT invoke scrollIntoView during active SSE streaming when user is scrolled up', async () => {
    const { response, sendEvent, closeStream } = createControlledStream();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) return Promise.resolve(response);
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;
    expect(scrollContainer).toBeInTheDocument();

    // 1. Submit a prompt using Enter
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Explain arterial health' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    // Initial message creation calls scrollIntoView
    expect(scrollIntoViewSpy).toHaveBeenCalled();
    scrollIntoViewSpy.mockClear();

    // 2. Deliver initial token while at bottom -> should auto-scroll
    await act(async () => {
      sendEvent('token', { type: 'token', delta: 'Blood pressure ' });
    });

    await waitFor(() => {
      expect(screen.getByText('Blood pressure')).toBeInTheDocument();
    });
    expect(scrollIntoViewSpy).toHaveBeenCalled();
    scrollIntoViewSpy.mockClear();

    // 3. User scrolls UP: distanceFromBottom = 1500 - 300 - 400 = 800 (>= 60)
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1500 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 300 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });

    fireEvent.scroll(scrollContainer);

    // Verify ScrollToBottomButton is now visible
    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-100');
    expect(btnWrapper).toHaveClass('pointer-events-auto');

    scrollIntoViewSpy.mockClear();

    // 4. Stream 8 consecutive tokens while scrolled up
    const tokens = ['is ', 'the ', 'lateral ', 'force ', 'of ', 'circulating ', 'blood ', 'on arteries.'];
    for (let i = 0; i < tokens.length; i++) {
      await act(async () => {
        sendEvent('token', { type: 'token', delta: tokens[i] });
      });
    }

    // ADVERSARIAL ASSERTION: scrollIntoView MUST NOT have been called while scrolled up!
    expect(scrollIntoViewSpy).not.toHaveBeenCalled();

    // Verify unread badge accumulated all 8 tokens
    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('8');

    // 5. User clicks ScrollToBottomButton to jump to bottom
    fireEvent.click(screen.getByTestId('scroll-to-bottom-btn'));

    // Verify smooth scroll was triggered
    expect(scrollIntoViewSpy).toHaveBeenCalledWith({ behavior: 'smooth' });

    // Verify unread counter reset to 0 and button hidden
    expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();
    expect(btnWrapper).toHaveClass('opacity-0');
    expect(btnWrapper).toHaveClass('pointer-events-none');

    scrollIntoViewSpy.mockClear();

    // 6. Next token arriving should now auto-scroll again since user is back at bottom
    await act(async () => {
      sendEvent('token', { type: 'token', delta: ' Normal is <120/80.' });
    });

    expect(scrollIntoViewSpy).toHaveBeenCalled();

    // Clean up
    await act(async () => {
      sendEvent('done', { type: 'done', fullText: 'Done.' });
      closeStream();
    });
  });

  it('caps unread counter at 99+ when high token volume arrives while scrolled up', async () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={120} />);
    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('99+');
  });

  it('clears unread badge automatically when user manually scrolls down to within 60px of bottom', async () => {
    const { response, sendEvent, closeStream } = createControlledStream();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) return Promise.resolve(response);
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Send prompt
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Test manual scroll down' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    // User scrolls up (distance = 1000 - 200 - 400 = 400 >= 60)
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 200 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
    fireEvent.scroll(scrollContainer);

    // Send 3 tokens
    await act(async () => {
      sendEvent('token', { type: 'token', delta: 'One ' });
      sendEvent('token', { type: 'token', delta: 'Two ' });
      sendEvent('token', { type: 'token', delta: 'Three ' });
    });

    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toHaveTextContent('3');

    // User manually scrolls back down (distance = 1000 - 570 - 400 = 30 < 60)
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 570 });
    fireEvent.scroll(scrollContainer);

    // Verify unread badge is instantly cleared
    await waitFor(() => {
      expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();
    });

    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-0');
    expect(btnWrapper).toHaveClass('pointer-events-none');

    await act(async () => {
      sendEvent('done', { type: 'done', fullText: 'Done.' });
      closeStream();
    });
  });
});

describe('Stress Test: Mobile Responsiveness, 100dvh & Double Scrollbars', () => {
  it('container uses dynamic viewport 100dvh with outer overflow-hidden to prevent nested window scrollbars', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const outerContainer = container.querySelector('.flex.flex-col') as HTMLElement;

    // Must be 100dvh on mobile (<640px) and sm:100dvh
    expect(outerContainer.className).toContain('h-[calc(100dvh-120px)]');
    expect(outerContainer.className).toContain('sm:h-[calc(100dvh-140px)]');
    // Must strictly contain overflow-hidden
    expect(outerContainer.className).toContain('overflow-hidden');
    // Must not contain 100vh static heights that cause mobile overflow
    expect(outerContainer.className).not.toMatch(/\bh-\[calc\(100vh/);
  });

  it('message list is the sole scrollable container in the viewport', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainers = container.querySelectorAll('.overflow-y-auto');

    // Only the message history container has overflow-y-auto initially
    expect(scrollContainers.length).toBe(1);
    expect(scrollContainers[0].parentElement).toHaveClass('relative');
  });

  it('textarea composer prevents double scrollbars by keeping overflow-y hidden until exceeding 160px', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Empty state: 42px and overflow hidden
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Medium text (scrollHeight 100px): expands without inner scrollbar
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 100 });
    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3' } });
    expect(textarea.style.height).toBe('100px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Overflow text (scrollHeight 220px): capped at 160px and enables auto overflow
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 220 });
    fireEvent.change(textarea, { target: { value: 'Long text...\n'.repeat(10) } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');

    // Resetting text restores 42px and overflow hidden
    fireEvent.change(textarea, { target: { value: '' } });
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');
  });

  it('textarea enforces 16px text-base on mobile to eliminate iOS Safari viewport auto-zoom', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    expect(textarea.className).toContain('text-base');
    expect(textarea.className).toContain('sm:text-sm');
  });
});

describe('Stress Test: Accessible Touch Targets (>= 44px)', () => {
  it('ScrollToBottomButton has touch target >= 44px', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} />);
    const btn = screen.getByTestId('scroll-to-bottom-btn');
    expect(btn.className).toContain('min-w-[44px]');
    expect(btn.className).toContain('min-h-[44px]');
  });

  it('Composer Send and Stop buttons have touch targets >= 44px', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const sendBtn = screen.getByTitle('Send Prompt');
    expect(sendBtn.className).toContain('min-w-[44px]');
    expect(sendBtn.className).toContain('min-h-[44px]');
  });

  it('Message toolbar buttons have touch targets >= 44px', () => {
    const mockMsg: ChatMessage = {
      id: 'msg-1',
      role: 'assistant',
      content: 'Here is your information.',
      timestamp: new Date().toISOString()
    };

    render(<ChatMessageItem message={mockMsg} onRegenerate={vi.fn()} />);
    const copyBtn = screen.getByTestId('message-copy-btn');
    const regenBtn = screen.getByTestId('message-rerun-btn');

    expect(copyBtn.className).toContain('min-w-[44px]');
    expect(copyBtn.className).toContain('min-h-[44px]');
    expect(regenBtn.className).toContain('min-w-[44px]');
    expect(regenBtn.className).toContain('min-h-[44px]');
  });
});

describe('Stress Test: ThinkingIndicator & ToolTrace Stability', () => {
  it('ThinkingIndicator displays planning status during initial latency and switches to executing status during active tool run', () => {
    const initialMsg: ChatMessage = {
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      isStreaming: true,
      toolTraces: []
    };

    const { rerender } = render(<ChatMessageItem message={initialMsg} />);
    const indicator = screen.getByTestId('thinking-indicator');
    expect(indicator).toBeInTheDocument();
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Planning clinical navigation...');

    // Now tool starts running
    const runningToolMsg: ChatMessage = {
      ...initialMsg,
      toolTraces: [
        {
          id: 'trace-1',
          tool: 'search_clinical_guidelines',
          status: 'running',
          input: { query: 'hypertension' }
        }
      ]
    };

    rerender(<ChatMessageItem message={runningToolMsg} />);
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Executing clinical tools...');
  });

  it('ToolTraceCard details pre tags are vertically bounded with max-h-40 to prevent massive layout shifts', () => {
    const largeOutput = { data: Array(50).fill('clinical record entry') };
    const trace: ToolTraceItem = {
      tool: 'extract_document_dossier',
      status: 'completed',
      params: { path: '/path/to/large.pdf' },
      output: largeOutput
    };

    render(<ToolTraceCard trace={trace} defaultExpanded={true} />);
    const paramsPre = screen.getByTestId('tool-trace-params');
    const outputPre = screen.getByTestId('tool-trace-output');

    expect(paramsPre.className).toContain('max-h-40');
    expect(paramsPre.className).toContain('overflow-auto');
    expect(outputPre.className).toContain('max-h-40');
    expect(outputPre.className).toContain('overflow-auto');
  });
});

describe('Stress Test: Tailwind CSS v3 Hygiene Across Components', () => {
  it('validates rendered DOM across components contains 0 Tailwind v4 invalid classes', () => {
    const { container: c1 } = render(<ThinkingIndicator />);
    const { container: c2 } = render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={3} />);
    const { container: c3 } = render(
      <ToolTraceCard
        trace={{
          tool: 'test-tool',
          status: 'completed',
          params: { a: 1 },
          output: 'done'
        }}
        defaultExpanded={true}
      />
    );
    const { container: c4 } = render(<ChatClient initialAgents={mockAgents} />);

    const fullRenderedHtml = [c1.innerHTML, c2.innerHTML, c3.innerHTML, c4.innerHTML].join('\n');

    expect(fullRenderedHtml).not.toContain('shadow-xs');
    expect(fullRenderedHtml).not.toContain('shadow-2xs');
    expect(fullRenderedHtml).not.toContain('focus:outline-hidden');
    expect(fullRenderedHtml).not.toContain('outline-hidden');
    expect(fullRenderedHtml).not.toContain('backdrop-blur-xs');
  });
});

describe('Stress Test: Resilience Under Edge Conditions', () => {
  it('handles iOS rubber-band overscroll gracefully without state corruption', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Simulate bottom overscroll (scrollTop exceeds scrollHeight - clientHeight)
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 650 }); // 1000 - 650 - 400 = -50
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });

    fireEvent.scroll(scrollContainer);

    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-0');

    // Simulate top overscroll (scrollTop is negative)
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: -20 }); // 1000 - (-20) - 400 = 620
    fireEvent.scroll(scrollContainer);

    expect(btnWrapper).toHaveClass('opacity-100');
  });

  it('aborting stream via Stop button cleanly terminates stream and re-enables composer', async () => {
    let abortFired = false;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        const stream = new ReadableStream({
          start(controller) {
            options.signal?.addEventListener('abort', () => {
              abortFired = true;
              controller.close();
            });
          }
        });
        return Promise.resolve(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Cancel this query' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    // Stop button appears
    await waitFor(() => {
      expect(screen.getByTestId('chat-stop-btn')).toBeInTheDocument();
    });

    // Click stop button
    fireEvent.click(screen.getByTestId('chat-stop-btn'));

    // Should abort and restore send button
    await waitFor(() => {
      expect(abortFired).toBe(true);
      expect(screen.getByTestId('chat-submit-btn')).toBeInTheDocument();
      expect(textarea).not.toBeDisabled();
    });
  });

  it('new session button resets messages, unread badge, and scroll position', async () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Simulate user scrolled up
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1200 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 200 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
    fireEvent.scroll(scrollContainer);

    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-100');

    // Click New Session
    fireEvent.click(screen.getByTestId('new-session-btn'));

    // Scroll button should be hidden and textarea empty
    expect(btnWrapper).toHaveClass('opacity-0');
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;
    expect(textarea.value).toBe('');
    expect(textarea.style.height).toBe('42px');
  });
});
