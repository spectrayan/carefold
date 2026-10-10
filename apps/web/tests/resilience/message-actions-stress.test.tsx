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
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';

// Helper to construct synthetic SSE Response ReadableStreams
function createMockSSEResponse(
  events: Array<{ event?: string; data: Record<string, any> }>,
  delayMs = 0
) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      for (const ev of events) {
        if (delayMs > 0) {
          await new Promise((r) => setTimeout(r, delayMs));
        }
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
  },
  {
    id: 'benefits-guide',
    title: 'Benefits Guide',
    version: '0.1.0',
    risk_class: 'wellness',
    skills: ['benefits-explainer'],
    effectiveTools: [],
    starters: ['Explain my deductible']
  }
];

describe('Resilience Challenge: Message Actions, Suggestions & Session Continuity', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. CLIPBOARD FAILURE RECOVERY & ADVERSARIAL CASES
  // =========================================================================
  describe('Resilience Challenge 1: Clipboard Failures & Edge Cases', () => {
    it('handles navigator.clipboard.writeText rejection (e.g. NotAllowedError) gracefully', async () => {
      vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(
        new DOMException('Document is not focused', 'NotAllowedError')
      );

      const userMsg: ChatMessage = {
        id: 'msg-u1',
        role: 'user',
        content: 'Test content for clipboard failure'
      };

      render(<ChatMessageItem message={userMsg} />);
      const copyBtn = screen.getByTestId('message-copy-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      // Should not throw unhandled rejection, and visual feedback must NOT be shown
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();
      expect(copyBtn).toHaveAttribute('aria-label', 'Copy message');
    });

    it('falls back to document.execCommand when navigator.clipboard is unavailable', async () => {
      const originalClipboard = navigator.clipboard;
      // Temporarily remove navigator.clipboard to simulate non-secure context or older browser
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      const execCommandSpy = vi.fn().mockReturnValue(true);
      document.execCommand = execCommandSpy;

      const userMsg: ChatMessage = {
        id: 'msg-u-fallback',
        role: 'user',
        content: 'Fallback copy content'
      };

      render(<ChatMessageItem message={userMsg} />);
      const copyBtn = screen.getByTestId('message-copy-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(execCommandSpy).toHaveBeenCalledWith('copy');
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Restore clipboard
      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
    });

    it('handles failure when document.execCommand throws an error', async () => {
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      document.execCommand = vi.fn().mockImplementation(() => {
        throw new Error('execCommand disabled by security policy');
      });

      const userMsg: ChatMessage = {
        id: 'msg-u-err',
        role: 'user',
        content: 'Error copy content'
      };

      render(<ChatMessageItem message={userMsg} />);
      const copyBtn = screen.getByTestId('message-copy-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();

      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
    });

    it('re-triggers copy timer correctly on rapid multiple copy clicks', async () => {
      vi.useFakeTimers();
      vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);

      const userMsg: ChatMessage = {
        id: 'msg-u-rapid',
        role: 'user',
        content: 'Rapid click copy test'
      };

      render(<ChatMessageItem message={userMsg} />);
      const copyBtn = screen.getByTestId('message-copy-btn');

      // Click 1
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance by 1000ms (halfway through the 2000ms duration)
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Click 2 (re-triggering before timeout expires)
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance by 1200ms (2200ms from start, but only 1200ms from click 2)
      act(() => {
        vi.advanceTimersByTime(1200);
      });
      // Should STILL be visible because timer was reset!
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance remaining 800ms
      act(() => {
        vi.advanceTimersByTime(800);
      });
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();

      vi.useRealTimers();
    });

    it('copies huge multiline markdown text without corruption or truncation', async () => {
      const hugeText = '# Header 1\n\n' + 'Line of text with symbols *!@#$%^&*()_+ and emojis 🩺💊\n'.repeat(500);
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);

      const msg: ChatMessage = {
        id: 'msg-huge',
        role: 'assistant',
        content: hugeText
      };

      render(<ChatMessageItem message={msg} />);
      const copyBtn = screen.getByTestId('message-copy-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(writeTextSpy).toHaveBeenCalledWith(hugeText);
    });
  });

  // =========================================================================
  // 2. RAPID DOUBLE CLICKS ON RERUN & REGENERATE WHILE STREAMING
  // =========================================================================
  describe('Resilience Challenge 2: Rapid Double Clicks on Rerun and Regenerate', () => {
    it('prevents duplicate concurrent fetch calls on rapid double-clicks to Rerun', async () => {
      let callCount = 0;
      let resolveStreamPromise: (val: any) => void;
      const streamPromise = new Promise((resolve) => {
        resolveStreamPromise = resolve;
      });

      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          return streamPromise;
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      // First submit an initial message to have a user message in history
      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Original prompt' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Let initial stream finish
      resolveStreamPromise!(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'First answer' } },
          { event: 'done', data: { type: 'done', fullText: 'First answer' } }
        ])
      );

      await waitFor(() => {
        expect(screen.getByText('First answer')).toBeInTheDocument();
      });

      expect(callCount).toBe(1);

      // Now set up a slower stream for the rerun to observe in-flight behavior
      let resolveRerunStream: (val: any) => void;
      const rerunStreamPromise = new Promise((resolve) => {
        resolveRerunStream = resolve;
      });

      mockFetch.mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          return rerunStreamPromise;
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      // Find the rerun button for the user message
      const rerunButtons = screen.getAllByTestId('message-rerun-btn');
      const userRerunBtn = rerunButtons.find((btn) => btn.getAttribute('data-action') === 'rerun');
      expect(userRerunBtn).toBeDefined();

      // Perform rapid double-click on the Rerun button
      fireEvent.click(userRerunBtn!);
      fireEvent.click(userRerunBtn!);

      // Verify that callCount only increased by 1 (total 2), NOT by 2
      expect(callCount).toBe(2);

      // Verify button is now disabled while stream is in flight
      expect(userRerunBtn).toBeDisabled();

      // Even another click while disabled does not increase callCount
      fireEvent.click(userRerunBtn!);
      expect(callCount).toBe(2);

      // Clean up in-flight stream
      resolveRerunStream!(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Rerun answer' } },
          { event: 'done', data: { type: 'done', fullText: 'Rerun answer' } }
        ])
      );

      await waitFor(() => {
        expect(screen.getByText('Rerun answer')).toBeInTheDocument();
      });
    });

    it('prevents duplicate concurrent fetch calls on rapid double-clicks to Regenerate', async () => {
      let callCount = 0;
      let resolveStreamPromise: (val: any) => void;
      const streamPromise = new Promise((resolve) => {
        resolveStreamPromise = resolve;
      });

      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          return streamPromise;
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      // Submit prompt
      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Explain my deductible' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Complete initial turn
      resolveStreamPromise!(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Initial deductible answer' } },
          { event: 'done', data: { type: 'done', fullText: 'Initial deductible answer' } }
        ])
      );

      await waitFor(() => {
        expect(screen.getByText('Initial deductible answer')).toBeInTheDocument();
      });

      expect(callCount).toBe(1);

      // Slower second stream
      let resolveRegenStream: (val: any) => void;
      const regenStreamPromise = new Promise((resolve) => {
        resolveRegenStream = resolve;
      });

      mockFetch.mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          return regenStreamPromise;
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      // Find the regenerate button
      const rerunButtons = screen.getAllByTestId('message-rerun-btn');
      const regenerateBtn = rerunButtons.find((btn) => btn.getAttribute('data-action') === 'regenerate');
      expect(regenerateBtn).toBeDefined();

      // Rapid double click
      fireEvent.click(regenerateBtn!);
      fireEvent.click(regenerateBtn!);

      // Only one new fetch call should be triggered
      expect(callCount).toBe(2);

      // Resolve stream
      resolveRegenStream!(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Regenerated deductible answer' } },
          { event: 'done', data: { type: 'done', fullText: 'Regenerated deductible answer' } }
        ])
      );

      await waitFor(() => {
        expect(screen.getByText('Regenerated deductible answer')).toBeInTheDocument();
      });
    });

    it('correctly rolls back assistant turn on regenerate and preserves prior multi-turn history', async () => {
      let callCount = 0;
      let capturedPayloads: any[] = [];

      const mockFetch = vi.fn().mockImplementation((url, options) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          capturedPayloads.push(JSON.parse(options.body));
          const responseText = `Answer for turn ${callCount}`;
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: responseText } },
              { event: 'done', data: { type: 'done', fullText: responseText } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      // Turn 1
      const input = screen.getByPlaceholderText(/Message/i);
      fireEvent.change(input, { target: { value: 'Turn 1 prompt' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));
      await waitFor(() => expect(screen.getByText('Answer for turn 1')).toBeInTheDocument());

      // Turn 2
      fireEvent.change(input, { target: { value: 'Turn 2 prompt' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));
      await waitFor(() => expect(screen.getByText('Answer for turn 2')).toBeInTheDocument());

      expect(callCount).toBe(2);

      // Regenerate Turn 2
      const rerunButtons = screen.getAllByTestId('message-rerun-btn');
      const regenButtons = rerunButtons.filter((btn) => btn.getAttribute('data-action') === 'regenerate');
      // The last regenerate button corresponds to turn 2
      const lastRegenBtn = regenButtons[regenButtons.length - 1];
      fireEvent.click(lastRegenBtn);

      await waitFor(() => {
        expect(callCount).toBe(3);
      });

      // The 3rd call should have:
      // prompt: 'Turn 2 prompt'
      // messages: Turn 1 prompt + Turn 1 answer (Turn 2 is re-generated from that point)
      const turn3Payload = capturedPayloads[2];
      expect(turn3Payload.prompt).toBe('Turn 2 prompt');
      expect(turn3Payload.messages).toHaveLength(2);
      expect(turn3Payload.messages[0].content).toBe('Turn 1 prompt');
      expect(turn3Payload.messages[1].content).toBe('Answer for turn 1');
    });
  });

  // =========================================================================
  // 3. SUGGESTED QUESTIONS CHIPS: RENDERING, LONG STRINGS & SPECIAL CHARS
  // =========================================================================
  describe('Resilience Challenge 3: Suggested Questions Chips Edge Cases', () => {
    it('handles long suggestion strings without crashing or overflowing layout', () => {
      const veryLongSuggestion = 'What are all the detailed considerations and documentation required '.repeat(20);
      const onSelect = vi.fn();

      render(
        <SuggestedQuestionsChips
          suggestions={[veryLongSuggestion, 'Short question?']}
          onSelectSuggestion={onSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(2);

      // The chip should render the full text inside its truncate span
      expect(chips[0]).toHaveTextContent(veryLongSuggestion.trim());

      // Clicking it passes the entire untruncated string
      fireEvent.click(chips[0]);
      expect(onSelect).toHaveBeenCalledTimes(1);
      expect(onSelect).toHaveBeenCalledWith(veryLongSuggestion.trim());
    });

    it('safely renders suggestions containing HTML, XSS payloads, and special characters', () => {
      const dangerousSuggestions = [
        '<script>alert("XSS")</script>',
        '"><img src="x" onerror="alert(1)">',
        'Is 100mg > 50mg & "safe" to take?'
      ];
      const onSelect = vi.fn();

      render(
        <SuggestedQuestionsChips
          suggestions={dangerousSuggestions}
          onSelectSuggestion={onSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(3);

      // Verifies rendered as text content, not parsed as DOM nodes
      expect(chips[0]).toHaveTextContent('<script>alert("XSS")</script>');
      expect(document.querySelector('script')).toBeNull();
      expect(document.querySelector('img[src="x"]')).toBeNull();

      fireEvent.click(chips[1]);
      expect(onSelect).toHaveBeenCalledWith('"><img src="x" onerror="alert(1)">');
    });

    it('correctly renders unicode, medical emojis, and multi-language questions', () => {
      const multiLangSuggestions = [
        '💊 What are the side effects of aspirin? 🩺',
        'مرحبا، كيف استعد لزيارة الطبيب؟', // Arabic
        '如何准备我的第一次问诊？' // Chinese
      ];
      const onSelect = vi.fn();

      render(
        <SuggestedQuestionsChips
          suggestions={multiLangSuggestions}
          onSelectSuggestion={onSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(3);
      expect(chips[0]).toHaveTextContent('💊 What are the side effects of aspirin? 🩺');
      expect(chips[1]).toHaveTextContent('مرحبا، كيف استعد لزيارة الطبيب؟');
      expect(chips[2]).toHaveTextContent('如何准备我的第一次问诊？');

      fireEvent.click(chips[0]);
      expect(onSelect).toHaveBeenCalledWith('💊 What are the side effects of aspirin? 🩺');
    });

    it('deduplicates identical suggestions and enforces maximum cap of 3', () => {
      const redundantList = [
        'Question A',
        'Question A', // Duplicate
        ' Question A ', // Trimmed duplicate
        'Question B',
        'Question C',
        'Question D', // Exceeds cap
        'Question E' // Exceeds cap
      ];
      const onSelect = vi.fn();

      render(
        <SuggestedQuestionsChips
          suggestions={redundantList}
          onSelectSuggestion={onSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(3);
      expect(chips[0]).toHaveTextContent('Question A');
      expect(chips[1]).toHaveTextContent('Question B');
      expect(chips[2]).toHaveTextContent('Question C');
      expect(screen.queryByText('Question D')).not.toBeInTheDocument();
    });

    it('filters out non-string items and empty strings without crashing', () => {
      const mixedList: any[] = [
        '',
        '   ',
        null,
        undefined,
        12345,
        'Valid question?'
      ];
      const onSelect = vi.fn();

      render(
        <SuggestedQuestionsChips
          suggestions={mixedList}
          onSelectSuggestion={onSelect}
        />
      );

      const chips = screen.getAllByTestId('suggested-question-chip');
      expect(chips).toHaveLength(1);
      expect(chips[0]).toHaveTextContent('Valid question?');
    });

    it('clicking suggestion chip in ChatClient immediately dispatches prompt and disables chips during flight', async () => {
      let callCount = 0;
      let capturedBody: any = null;
      let resolveSecondStream: (val: any) => void;
      const secondStreamPromise = new Promise((resolve) => {
        resolveSecondStream = resolve;
      });

      const mockFetch = vi.fn().mockImplementation((url, options) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          if (callCount === 1) {
            return Promise.resolve(
              createMockSSEResponse([
                { event: 'token', data: { type: 'token', delta: 'Initial answer' } },
                {
                  event: 'suggestions',
                  data: {
                    type: 'suggestions',
                    suggestions: ['Suggested follow-up prompt?']
                  }
                },
                { event: 'done', data: { type: 'done', fullText: 'Initial answer' } }
              ])
            );
          } else {
            capturedBody = JSON.parse(options.body);
            return secondStreamPromise;
          }
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      // Send turn 1
      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Start' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Wait for suggestion chip to appear
      await waitFor(() => {
        expect(screen.getByText('Suggested follow-up prompt?')).toBeInTheDocument();
      });

      // Click the suggestion chip
      fireEvent.click(screen.getByText('Suggested follow-up prompt?'));

      // Chip container disappears while streaming
      expect(screen.queryByTestId('suggested-questions-container')).not.toBeInTheDocument();

      // Verify the second fetch was made with the exact suggestion
      expect(callCount).toBe(2);
      expect(capturedBody.prompt).toBe('Suggested follow-up prompt?');

      // Finish second stream
      resolveSecondStream!(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Second answer' } },
          { event: 'done', data: { type: 'done', fullText: 'Second answer' } }
        ])
      );

      await waitFor(() => {
        expect(screen.getByText('Second answer')).toBeInTheDocument();
      });
    });
  });

  // =========================================================================
  // 4. THREAD CONTINUITY IN LOCALSTORAGE ACROSS PAGE RELOADS
  // =========================================================================
  describe('Resilience Challenge 4: Thread Continuity & Persistence Across Reloads', () => {
    it('restores conversation history and maintains active threadId across simulated reload', async () => {
      let callCount = 0;
      let capturedThreadId: string | null = null;

      const mockFetch = vi.fn().mockImplementation((url, options) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          callCount++;
          const body = JSON.parse(options.body);
          capturedThreadId = body.threadId;
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Response before reload' } },
              { event: 'done', data: { type: 'done', fullText: 'Response before reload' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      // Session 1: Render ChatClient
      const { unmount } = render(<ChatClient initialAgents={mockAgents} />);

      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Prompt before reload' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByText('Response before reload')).toBeInTheDocument();
      });

      expect(capturedThreadId).toMatch(/^thread-visit-steward-/);
      const originalThreadId = capturedThreadId;

      // Verify localStorage was written
      expect(localStorage.getItem('carefold_thread_visit-steward')).toBe(originalThreadId);
      const savedMsgs = localStorage.getItem(`carefold_msgs_${originalThreadId}`);
      expect(savedMsgs).not.toBeNull();
      const parsedMsgs = JSON.parse(savedMsgs!);
      expect(parsedMsgs).toHaveLength(2);
      expect(parsedMsgs[0].content).toBe('Prompt before reload');
      expect(parsedMsgs[1].content).toBe('Response before reload');

      // Simulate Page Reload by unmounting and mounting a fresh instance
      unmount();

      let postReloadThreadId: string | null = null;
      mockFetch.mockImplementation((url, options) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          const body = JSON.parse(options.body);
          postReloadThreadId = body.threadId;
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Response after reload' } },
              { event: 'done', data: { type: 'done', fullText: 'Response after reload' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });

      render(<ChatClient initialAgents={mockAgents} />);

      // Messages should be restored immediately from localStorage
      await waitFor(() => {
        expect(screen.getByText('Prompt before reload')).toBeInTheDocument();
        expect(screen.getByText('Response before reload')).toBeInTheDocument();
      });

      // Send a follow-up message after reload
      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Prompt after reload' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByText('Response after reload')).toBeInTheDocument();
      });

      // Crucial assertion: the post-reload message used the exact SAME threadId
      expect(postReloadThreadId).toBe(originalThreadId);
    });

    it('isolates threads and conversation history between different agents', async () => {
      const mockFetch = vi.fn().mockImplementation((url, options) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          const body = JSON.parse(options.body);
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: `Answer for ${body.agentId}` } },
              { event: 'done', data: { type: 'done', fullText: `Answer for ${body.agentId}` } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      // Agent 1: visit-steward
      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Question for steward' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));
      await waitFor(() => expect(screen.getByText('Answer for visit-steward')).toBeInTheDocument());

      const stewardThreadId = localStorage.getItem('carefold_thread_visit-steward');
      expect(stewardThreadId).not.toBeNull();

      // Switch to Agent 2: benefits-guide
      const agentSelector = screen.getByLabelText(/select (?:health )?agent/i);
      fireEvent.change(agentSelector, { target: { value: 'benefits-guide' } });

      // History should be empty for the new agent
      expect(screen.queryByText('Question for steward')).not.toBeInTheDocument();
      expect(screen.queryByText('Answer for visit-steward')).not.toBeInTheDocument();

      // Send message to benefits-guide
      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Question for benefits' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));
      await waitFor(() => expect(screen.getByText('Answer for benefits-guide')).toBeInTheDocument());

      const benefitsThreadId = localStorage.getItem('carefold_thread_benefits-guide');
      expect(benefitsThreadId).not.toBeNull();
      expect(benefitsThreadId).not.toBe(stewardThreadId);

      // Switch BACK to visit-steward
      fireEvent.change(agentSelector, { target: { value: 'visit-steward' } });

      // Steward history is restored
      await waitFor(() => {
        expect(screen.getByText('Question for steward')).toBeInTheDocument();
        expect(screen.getByText('Answer for visit-steward')).toBeInTheDocument();
      });

      // Benefits history is NOT mixed in
      expect(screen.queryByText('Question for benefits')).not.toBeInTheDocument();
    });

    it('gracefully handles corrupted localStorage JSON without crashing component', async () => {
      // Intentionally write invalid JSON into localStorage for thread
      const corruptThreadId = 'thread-visit-steward-corrupted';
      localStorage.setItem('carefold_thread_visit-steward', corruptThreadId);
      localStorage.setItem(`carefold_msgs_${corruptThreadId}`, '{invalid json[<');

      // Rendering should not throw SyntaxError or crash
      render(<ChatClient initialAgents={mockAgents} />);

      // The UI should display empty state without crashing
      expect(screen.getByText(/Chat with Visit Steward/i)).toBeInTheDocument();

      // Sending a message should function normally and overwrite cleanly
      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Recovered response' } },
              { event: 'done', data: { type: 'done', fullText: 'Recovered response' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Hello recovery' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      await waitFor(() => {
        expect(screen.getByText('Recovered response')).toBeInTheDocument();
      });
    });

    it('handles localStorage QuotaExceededError when saving messages without crashing', async () => {
      // Mock setItem to throw QuotaExceededError
      const originalSetItem = localStorage.setItem;
      localStorage.setItem = vi.fn().mockImplementation((key, val) => {
        if (key.startsWith('carefold_msgs_')) {
          throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
        }
        return originalSetItem.call(localStorage, key, val);
      });

      const mockFetch = vi.fn().mockImplementation((url) => {
        if ((url === '/api/chat' || url === '/api/v1/chat')) {
          return Promise.resolve(
            createMockSSEResponse([
              { event: 'token', data: { type: 'token', delta: 'Quota test response' } },
              { event: 'done', data: { type: 'done', fullText: 'Quota test response' } }
            ])
          );
        }
        return Promise.resolve(new Response('{}', { status: 200 }));
      });
      vi.stubGlobal('fetch', mockFetch);

      render(<ChatClient initialAgents={mockAgents} />);

      fireEvent.change(screen.getByPlaceholderText(/Message/i), { target: { value: 'Test quota limit' } });
      fireEvent.click(screen.getByTitle('Send Prompt'));

      // Should complete and render cleanly despite localStorage save failing
      await waitFor(() => {
        expect(screen.getByText('Quota test response')).toBeInTheDocument();
      });

      localStorage.setItem = originalSetItem;
    });
  });
});
