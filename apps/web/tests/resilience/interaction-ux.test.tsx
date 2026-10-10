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

describe('Adversarial Stress Suite: Composer Keyboard & Height Boundaries', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 }))));
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // ---------------------------------------------------------------------------
  // 1. KEYBOARD DISPATCH: ENTER, SHIFT+ENTER, MODIFIERS, AND WHITESPACE
  // ---------------------------------------------------------------------------
  it('submits on Enter keydown when valid prompt text is present', async () => {
    let capturedBody: any = null;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat') {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(new Response('event: done\ndata: {"type":"done","fullText":"ok"}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' }
        }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'Valid clinical question' } });

    // Press Enter
    const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: false, bubbles: true });
    const preventSpy = vi.spyOn(enterEvent, 'preventDefault');
    textarea.dispatchEvent(enterEvent);

    expect(preventSpy).toHaveBeenCalled();
    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });
    expect(capturedBody.prompt).toBe('Valid clinical question');
  });

  it('suppresses submission and prevents default when text is whitespace only', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Whitespace permutations: spaces, newlines, tabs
    fireEvent.change(textarea, { target: { value: '   \n\t  \r\n   ' } });

    const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: false, bubbles: true });
    const preventSpy = vi.spyOn(enterEvent, 'preventDefault');
    textarea.dispatchEvent(enterEvent);

    // Default prevented so newline is not inserted, but API is not called
    expect(preventSpy).toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('allows Shift+Enter to pass through without submitting or calling preventDefault', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'First line of symptoms' } });

    const shiftEnterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: true, bubbles: true });
    const preventSpy = vi.spyOn(shiftEnterEvent, 'preventDefault');
    textarea.dispatchEvent(shiftEnterEvent);

    expect(preventSpy).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('allows modifier combinations with Shift (Ctrl+Shift+Enter, Meta+Shift+Enter, Alt+Shift+Enter) to pass through without submitting', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'Multiline draft' } });

    for (const modifier of ['ctrlKey', 'metaKey', 'altKey'] as const) {
      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
        code: 'Enter',
        shiftKey: true,
        [modifier]: true,
        bubbles: true
      });
      const preventSpy = vi.spyOn(event, 'preventDefault');
      textarea.dispatchEvent(event);

      expect(preventSpy).not.toHaveBeenCalled();
      expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
    }
  });

  // ---------------------------------------------------------------------------
  // 2. IME COMPOSITION AND CANDIDATE CONFIRMATION (CJK / ACCENTS)
  // ---------------------------------------------------------------------------
  it('suppresses submission when IME is actively composing (native isComposing = true)', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'nihon' } });

    // Attack: Enter pressed while isComposing is true on keyboard event and nativeEvent
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: true,
      nativeEvent: { isComposing: true }
    });

    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('suppresses submission on mobile / browser IME composition code (keyCode === 229)', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'hangul' } });

    // keyCode 229 represents IME input method active
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      keyCode: 229,
      shiftKey: false
    });

    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('handles full IME lifecycle: candidate conversion Enter does not send, final Enter sends', async () => {
    let capturedBody: any = null;
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url, options) => {
      if (url === '/api/chat') {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(new Response('event: done\ndata: {"type":"done","fullText":"ok"}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' }
        }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // 1. User types in IME buffer
    fireEvent.compositionStart(textarea);
    fireEvent.change(textarea, { target: { value: 'byouin' } });

    // 2. Candidate dropdown Enter (confirming kanji "病院") -> must not submit
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: true,
      nativeEvent: { isComposing: true }
    });
    expect(capturedBody).toBeNull();

    // 3. Composition finishes
    fireEvent.compositionEnd(textarea, { data: '病院' });
    fireEvent.change(textarea, { target: { value: '病院' } });

    // 4. User presses Enter to send -> must submit
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: false,
      nativeEvent: { isComposing: false }
    });

    await waitFor(() => {
      expect(capturedBody).not.toBeNull();
    });
    expect(capturedBody.prompt).toBe('病院');
  });

  // ---------------------------------------------------------------------------
  // 3. HEIGHT GROWTH AND RESET BOUNDARIES (42px to 160px)
  // ---------------------------------------------------------------------------
  it('verifies height clamp boundaries: 42px min, linear growth, 160px max with overflow toggle', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Initial state: empty -> 42px, overflowY hidden
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case 1: Sub-minimum scrollHeight (e.g. 15px reported by browser) -> clamped to 42px
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 15 });
    fireEvent.change(textarea, { target: { value: 'a' } });
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case 2: Intermediate scrollHeight 84px -> height is exactly 84px, overflowY hidden
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 84 });
    fireEvent.change(textarea, { target: { value: 'Line 1\nLine 2\nLine 3' } });
    expect(textarea.style.height).toBe('84px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case 3: Boundary at exactly 159px -> height 159px, overflowY hidden
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 159 });
    fireEvent.change(textarea, { target: { value: 'Lines at 159px' } });
    expect(textarea.style.height).toBe('159px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case 4: Boundary at exactly 160px -> height 160px, overflowY hidden
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 160 });
    fireEvent.change(textarea, { target: { value: 'Lines at 160px' } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case 5: Boundary at 161px (> 160) -> height clamped to 160px, overflowY becomes auto
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 161 });
    fireEvent.change(textarea, { target: { value: 'Lines exceeding 160px by 1' } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');

    // Case 6: Massive scrollHeight (500px) -> height clamped to 160px, overflowY auto
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 500 });
    fireEvent.change(textarea, { target: { value: 'Massive content\n'.repeat(30) } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('resets height to 42px and overflow to hidden across all clearing triggers (backspace, Enter submit, New Session)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') {
        return Promise.resolve(new Response('event: done\ndata: {"type":"done","fullText":"ok"}\n\n', {
          headers: { 'Content-Type': 'text/event-stream' }
        }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Trigger A: Backspace to empty
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 130 });
    fireEvent.change(textarea, { target: { value: 'Drafting question' } });
    expect(textarea.style.height).toBe('130px');

    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 42 });
    fireEvent.change(textarea, { target: { value: '' } });
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Trigger B: Enter submit resets height
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 155 });
    fireEvent.change(textarea, { target: { value: 'Multiline\nquestion\nsubmitted' } });
    expect(textarea.style.height).toBe('155px');

    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });
    await waitFor(() => {
      expect(textarea.value).toBe('');
      expect(textarea.style.height).toBe('42px');
      expect(textarea.style.overflowY).toBe('hidden');
    });

    // Trigger C: New session resets height
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 140 });
    fireEvent.change(textarea, { target: { value: 'Unsent text for next turn' } });
    expect(textarea.style.height).toBe('140px');

    fireEvent.click(screen.getByTestId('new-session-btn'));
    expect(textarea.value).toBe('');
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');
  });

  // ---------------------------------------------------------------------------
  // 4. MULTILINE PASTE HANDLING
  // ---------------------------------------------------------------------------
  it('stress-tests 200-line massive multiline paste: clamps cleanly without desync', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    const massiveMultiline = Array.from({ length: 200 }, (_, i) => `Entry ${i + 1}: Patient symptoms log`).join('\n');
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 1800 });

    fireEvent.change(textarea, { target: { value: massiveMultiline } });

    expect(textarea.value).toBe(massiveMultiline);
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('stress-tests extreme 10,000 character single line paste with word-wrap', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    const extremeSingleLine = 'ClinicalObservation'.repeat(500); // 9500 chars
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 650 });

    fireEvent.change(textarea, { target: { value: extremeSingleLine } });

    expect(textarea.value).toBe(extremeSingleLine);
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('stress-tests rapid paste, modify, and delete churn over 20 consecutive cycles', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    for (let cycle = 0; cycle < 20; cycle++) {
      // Paste
      const pasted = `Cycle ${cycle} pasted content\nwith multiple\nlines`;
      Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 120 });
      fireEvent.change(textarea, { target: { value: pasted } });
      expect(textarea.style.height).toBe('120px');

      // Expand more
      Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 250 });
      fireEvent.change(textarea, { target: { value: pasted + '\n' + 'extra'.repeat(50) } });
      expect(textarea.style.height).toBe('160px');
      expect(textarea.style.overflowY).toBe('auto');

      // Clear
      Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 42 });
      fireEvent.change(textarea, { target: { value: '' } });
      expect(textarea.style.height).toBe('42px');
      expect(textarea.style.overflowY).toBe('hidden');
    }
  });
});

describe('Adversarial Stress Suite: Scroll Anti-Hijacking & Unread Counter', () => {
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

  // ---------------------------------------------------------------------------
  // 1. SCROLL POSITION BOUNDARIES (< 60px tolerance)
  // ---------------------------------------------------------------------------
  it('tests exact 60px scroll distance boundary: 59px is at bottom, 60px/61px is scrolled up', () => {
    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;
    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;

    // scrollHeight = 1000, clientHeight = 400
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });

    // Sub-case A: distanceFromBottom = 1000 - 541 - 400 = 59px (< 60) -> At bottom
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 541 });
    fireEvent.scroll(scrollContainer);
    expect(btnWrapper).toHaveClass('opacity-0');
    expect(btnWrapper).toHaveClass('pointer-events-none');

    // Sub-case B: distanceFromBottom = 1000 - 540 - 400 = 60px (not < 60) -> Scrolled away
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 540 });
    fireEvent.scroll(scrollContainer);
    expect(btnWrapper).toHaveClass('opacity-100');
    expect(btnWrapper).toHaveClass('pointer-events-auto');

    // Sub-case C: distanceFromBottom = 1000 - 539 - 400 = 61px -> Scrolled away
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 539 });
    fireEvent.scroll(scrollContainer);
    expect(btnWrapper).toHaveClass('opacity-100');
    expect(btnWrapper).toHaveClass('pointer-events-auto');

    // Sub-case D: Over-scroll at bottom (distance < 0, e.g. -20px) -> At bottom
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 620 }); // 1000 - 620 - 400 = -20
    fireEvent.scroll(scrollContainer);
    expect(btnWrapper).toHaveClass('opacity-0');
    expect(btnWrapper).toHaveClass('pointer-events-none');
  });

  // ---------------------------------------------------------------------------
  // 2. ANTI-HIJACKING DURING HIGH-FREQUENCY SSE TOKEN BURSTS (150 TOKENS)
  // ---------------------------------------------------------------------------
  it('strictly guarantees zero scroll hijacking across a high-frequency burst of 150 SSE tokens when scrolled up', async () => {
    const { response, sendEvent, closeStream } = createControlledStream();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') return Promise.resolve(response);
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Send initial prompt
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Stream stress test' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    // Initial user message scrollIntoView is called
    expect(scrollIntoViewSpy).toHaveBeenCalled();
    scrollIntoViewSpy.mockClear();

    // User scrolls up far from bottom: distance = 2000 - 500 - 400 = 1100px (>= 60)
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 2000 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 500 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
    fireEvent.scroll(scrollContainer);

    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-100');

    // Deliver a high-frequency burst of 150 consecutive tokens while scrolled up
    for (let i = 1; i <= 150; i++) {
      await act(async () => {
        sendEvent('token', { type: 'token', delta: `t${i} ` });
      });
    }

    // ADVERSARIAL VERIFICATION: Anti-hijacking guarantee!
    // scrollIntoView must NOT have been called even once during the entire 150 token flood!
    expect(scrollIntoViewSpy).not.toHaveBeenCalled();

    // Verify unread badge scaled and capped at '99+'
    const badge = screen.getByTestId('unread-counter-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('99+');

    // Deliver tool traces and done events while scrolled up: still no scroll hijack!
    await act(async () => {
      sendEvent('tool_start', { tool: 'check_vitals', params: {} });
      sendEvent('tool_end', { tool: 'check_vitals', status: 'completed', result: '120/80' });
      sendEvent('suggestions', { suggestions: ['Ask about resting pulse', 'Ask about medication'] });
      sendEvent('done', { type: 'done', fullText: 'Finished stream' });
    });

    expect(scrollIntoViewSpy).not.toHaveBeenCalled();

    closeStream();
  });

  // ---------------------------------------------------------------------------
  // 3. UNREAD COUNTER SCALING AND CLAMPING (1 to 99, 100+ to 99+)
  // ---------------------------------------------------------------------------
  it('scales unread badge text smoothly from 1 to 99 and caps at 99+ for 100, 250, 10000 unread tokens', () => {
    // 0 unread: badge absent
    const { rerender } = render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={0} />);
    expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();

    // Exact count for 1 through 99
    for (const count of [1, 7, 42, 99]) {
      rerender(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={count} />);
      const badge = screen.getByTestId('unread-counter-badge');
      expect(badge).toHaveTextContent(String(count));
    }

    // Capped at 99+ for 100+
    for (const count of [100, 101, 250, 999, 10000]) {
      rerender(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={count} />);
      const badge = screen.getByTestId('unread-counter-badge');
      expect(badge).toHaveTextContent('99+');
    }
  });

  // ---------------------------------------------------------------------------
  // 4. RESET ON BOTTOM SCROLL (BUTTON CLICK & MANUAL SCROLL)
  // ---------------------------------------------------------------------------
  it('resets unread counter and hides button when user clicks ScrollToBottomButton, and resumes auto-scroll on subsequent tokens', async () => {
    const { response, sendEvent, closeStream } = createControlledStream();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') return Promise.resolve(response);
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Send prompt
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Test click jump' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });
    scrollIntoViewSpy.mockClear();

    // Scroll up
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1200 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 300 });
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
    fireEvent.scroll(scrollContainer);

    // Send 15 tokens
    for (let i = 0; i < 15; i++) {
      await act(async () => {
        sendEvent('token', { type: 'token', delta: `word${i} ` });
      });
    }

    expect(screen.getByTestId('unread-counter-badge')).toHaveTextContent('15');
    const scrollBtn = screen.getByTestId('scroll-to-bottom-btn');

    // Click ScrollToBottomButton
    fireEvent.click(scrollBtn);

    // Assert smooth scroll triggered
    expect(scrollIntoViewSpy).toHaveBeenCalledWith({ behavior: 'smooth' });
    scrollIntoViewSpy.mockClear();

    // Assert unread badge disappeared and button hidden
    expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();
    const btnWrapper = scrollBtn.parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-0');

    // Next token arrives while user is back at bottom -> auto-scroll MUST execute
    await act(async () => {
      sendEvent('token', { type: 'token', delta: 'resumed token' });
    });

    expect(scrollIntoViewSpy).toHaveBeenCalledWith({ behavior: 'smooth' });

    closeStream();
  });

  it('resets unread counter instantly when user manually scrolls back within 60px of the bottom', async () => {
    const { response, sendEvent, closeStream } = createControlledStream();
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url) => {
      if (url === '/api/chat') return Promise.resolve(response);
      return Promise.resolve(new Response('{}', { status: 200 }));
    }));

    const { container } = render(<ChatClient initialAgents={mockAgents} />);
    const scrollContainer = container.querySelector('.overflow-y-auto') as HTMLElement;

    // Send prompt
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);
    fireEvent.change(textarea, { target: { value: 'Test manual scroll reset' } });
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    // Scrolled up
    Object.defineProperty(scrollContainer, 'scrollHeight', { configurable: true, value: 1200 });
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 400 }); // distance = 400
    Object.defineProperty(scrollContainer, 'clientHeight', { configurable: true, value: 400 });
    fireEvent.scroll(scrollContainer);

    // Stream 6 tokens
    for (let i = 0; i < 6; i++) {
      await act(async () => {
        sendEvent('token', { type: 'token', delta: `tok${i} ` });
      });
    }

    expect(screen.getByTestId('unread-counter-badge')).toHaveTextContent('6');

    // User manually scrolls down to distance = 1200 - 750 - 400 = 50px (< 60px)
    Object.defineProperty(scrollContainer, 'scrollTop', { configurable: true, value: 750 });
    fireEvent.scroll(scrollContainer);

    // Verify unread badge is cleared and button is hidden
    await waitFor(() => {
      expect(screen.queryByTestId('unread-counter-badge')).not.toBeInTheDocument();
    });
    const btnWrapper = screen.getByTestId('scroll-to-bottom-btn').parentElement as HTMLElement;
    expect(btnWrapper).toHaveClass('opacity-0');

    closeStream();
  });
});
