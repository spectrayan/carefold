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
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import { ToolTraceCard, type ToolTraceItem } from '@/components/ToolTraceCard';
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

describe('Stress Suite: Composer & Textarea Edge Cases', () => {
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

  // ---------------------------------------------------------------------------
  // 1. RAPID TYPING & STATE INTEGRITY
  // ---------------------------------------------------------------------------
  it('handles burst rapid typing of 100 characters without dropping input state or desyncing height', async () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Simulate 100 rapid keystrokes
    let currentText = '';
    for (let i = 0; i < 100; i++) {
      currentText += String.fromCharCode(65 + (i % 26));
      Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 42 + Math.floor(i / 20) * 15 });
      fireEvent.change(textarea, { target: { value: currentText } });
    }

    expect(textarea.value).toHaveLength(100);
    expect(textarea.value).toBe(currentText);
    expect(parseInt(textarea.style.height, 10)).toBeGreaterThanOrEqual(42);
    expect(parseInt(textarea.style.height, 10)).toBeLessThanOrEqual(160);
  });

  // ---------------------------------------------------------------------------
  // 2. MULTILINE PASTES & HEIGHT CLAMP BOUNDARIES (42px - 160px)
  // ---------------------------------------------------------------------------
  it('strictly clamps height at 160px with overflow-y-auto on massive multiline paste', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Paste 50 lines with huge scrollHeight (800px)
    const massiveText = Array.from({ length: 50 }, (_, i) => `Line ${i + 1}: Important clinical symptom data`).join('\n');
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 800 });

    fireEvent.change(textarea, { target: { value: massiveText } });

    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('strictly clamps height at 160px with overflow-y-auto on huge single line paste with word-wrap', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // 5000 character single line paragraph
    const longSingleLine = 'Word '.repeat(1000);
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 450 });

    fireEvent.change(textarea, { target: { value: longSingleLine } });

    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('tests height boundary exactly at 160px (scrollHeight = 160 vs 161)', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Case A: scrollHeight exactly 160px -> height 160px, overflowY hidden
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 160 });
    fireEvent.change(textarea, { target: { value: 'Lines reaching exactly 160' } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('hidden');

    // Case B: scrollHeight 161px -> height 160px, overflowY auto
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 161 });
    fireEvent.change(textarea, { target: { value: 'Lines exceeding 160 by 1px' } });
    expect(textarea.style.height).toBe('160px');
    expect(textarea.style.overflowY).toBe('auto');
  });

  it('tests lower height boundary (scrollHeight < 42 clamps to 42px)', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // scrollHeight reports 20px
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 20 });
    fireEvent.change(textarea, { target: { value: 'short' } });
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');
  });

  // ---------------------------------------------------------------------------
  // 3. HEIGHT RESETS ON SUBMISSION, CLEAR, & NEW SESSION
  // ---------------------------------------------------------------------------
  it('resets height to 42px and overflow to hidden when user clears text via backspace/select-all-delete', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Expand
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 140 });
    fireEvent.change(textarea, { target: { value: 'Multiline\nText\nHere' } });
    expect(textarea.style.height).toBe('140px');

    // User clears text completely
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 42 });
    fireEvent.change(textarea, { target: { value: '' } });

    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');
  });

  it('resets height to 42px on Enter key submission', async () => {
    const mockFetch = vi.fn().mockImplementation(() =>
      Promise.resolve(
        createMockSSEResponse([
          { event: 'token', data: { type: 'token', delta: 'Response' } },
          { event: 'done', data: { type: 'done', fullText: 'Response' } }
        ])
      )
    );
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Expand to 150px
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 150 });
    fireEvent.change(textarea, { target: { value: 'Multiline\nQuestion\nFor\nDoctor' } });
    expect(textarea.style.height).toBe('150px');

    // Submit with Enter (no shift)
    fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

    await waitFor(() => {
      expect(textarea.value).toBe('');
      expect(textarea.style.height).toBe('42px');
      expect(textarea.style.overflowY).toBe('hidden');
    });
  });

  it('resets height to 42px when "New Session" is triggered while expanded', () => {
    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Expand
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 150 });
    fireEvent.change(textarea, { target: { value: 'Unsent draft text\nspread over\nmultiple lines' } });
    expect(textarea.style.height).toBe('150px');

    // Click New Session
    const newSessionBtn = screen.getByTestId('new-session-btn');
    fireEvent.click(newSessionBtn);

    expect(textarea.value).toBe('');
    expect(textarea.style.height).toBe('42px');
    expect(textarea.style.overflowY).toBe('hidden');
  });

  // ---------------------------------------------------------------------------
  // 4. KEYBOARD DISPATCH: ENTER VS SHIFT+ENTER MODIFIERS
  // ---------------------------------------------------------------------------
  it('allows Shift+Enter, Ctrl+Shift+Enter, and Alt+Shift+Enter to pass through without submitting', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'Draft line' } });

    // Shift + Enter
    const shiftEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: true, bubbles: true });
    const shiftPreventSpy = vi.spyOn(shiftEvent, 'preventDefault');
    textarea.dispatchEvent(shiftEvent);
    expect(shiftPreventSpy).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());

    // Ctrl + Shift + Enter
    const ctrlShiftEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: true, ctrlKey: true, bubbles: true });
    const ctrlShiftPreventSpy = vi.spyOn(ctrlShiftEvent, 'preventDefault');
    textarea.dispatchEvent(ctrlShiftEvent);
    expect(ctrlShiftPreventSpy).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());

    // Alt + Shift + Enter
    const altShiftEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: true, altKey: true, bubbles: true });
    const altShiftPreventSpy = vi.spyOn(altShiftEvent, 'preventDefault');
    textarea.dispatchEvent(altShiftEvent);
    expect(altShiftPreventSpy).not.toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('prevents default newline on Enter without Shift when textarea is purely whitespace and files are empty', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '   \n  \t  ' } });

    const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', shiftKey: false, bubbles: true });
    const preventSpy = vi.spyOn(enterEvent, 'preventDefault');
    textarea.dispatchEvent(enterEvent);

    // Default prevented so newline is not inserted, but API is not called
    expect(preventSpy).toHaveBeenCalled();
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  // ---------------------------------------------------------------------------
  // 5. CJK / IME COMPOSITION ADVERSARIAL STRESS
  // ---------------------------------------------------------------------------
  it('protects CJK / IME candidate selection: suppresses submit on native isComposing and keyCode 229', () => {
    const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })));
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: '診察' } });

    // Attack 1: native isComposing = true on KeyboardEvent
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: true,
      nativeEvent: { isComposing: true }
    });
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());

    // Attack 2: keyCode === 229 (standard IME composition code)
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      keyCode: 229,
      shiftKey: false
    });
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());
  });

  it('completes CJK composition lifecycle: candidate confirm does not submit, subsequent Enter submits', async () => {
    let capturedBody: any = null;
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'はい' } },
            { event: 'done', data: { type: 'done', fullText: 'はい' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Step 1: User types romaji, IME active
    fireEvent.change(textarea, { target: { value: 'shinsatsu' } });

    // Step 2: User presses Enter to confirm kanji conversion (isComposing = true)
    fireEvent.keyDown(textarea, {
      key: 'Enter',
      code: 'Enter',
      shiftKey: false,
      isComposing: true,
      nativeEvent: { isComposing: true }
    });
    expect(mockFetch).not.toHaveBeenCalledWith('/api/chat', expect.anything());

    // Step 3: Text updated to converted kanji, composition ends
    fireEvent.change(textarea, { target: { value: '診察の予約' } });

    // Step 4: User presses Enter to submit (isComposing = false)
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
    expect(capturedBody.prompt).toBe('診察の予約');
  });

  // ---------------------------------------------------------------------------
  // 6. SUBMISSION WITH ATTACHMENTS ONLY (EMPTY TEXTAREA)
  // ---------------------------------------------------------------------------
  it('allows submission when textarea is empty but a file is attached', async () => {
    let capturedBody: any = null;
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        capturedBody = JSON.parse(options.body);
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Parsed attachment' } },
            { event: 'done', data: { type: 'done', fullText: 'Parsed attachment' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    // Attach a file via input
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    if (fileInput) {
      const file = new File(['blood test results'], 'lab_report.pdf', { type: 'application/pdf' });
      // Mock upload API
      mockFetch.mockResolvedValueOnce(
        new Response(JSON.stringify({ filename: 'lab_report.pdf', path: 'attachments/lab_report.pdf', size_bytes: 18 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' }
        })
      );
      fireEvent.change(fileInput, { target: { files: [file] } });

      await waitFor(() => {
        expect(screen.getByText('lab_report.pdf')).toBeInTheDocument();
      });

      // Textarea is empty: pressing Enter should submit
      expect(textarea.value).toBe('');
      fireEvent.keyDown(textarea, { key: 'Enter', code: 'Enter', shiftKey: false });

      await waitFor(() => {
        expect(capturedBody).not.toBeNull();
      });
      expect(capturedBody.prompt).toBe('');
      expect(capturedBody.attachments).toContain('attachments/lab_report.pdf');
    }
  });
});

describe('Stress Suite: ThinkingIndicator & Streaming State Transitions', () => {
  // ---------------------------------------------------------------------------
  // 1. STATE TRANSITIONS: LATENCY -> STREAMING -> FINISHED
  // ---------------------------------------------------------------------------
  it('correctly transitions through State 1 (latency), State 2 (token stream), and State 3 (finished)', () => {
    const handleRegenerate = vi.fn();
    // State 1: Latency State (isStreaming=true, content='')
    const latencyMsg: ChatMessage = {
      id: 'msg-stream-lifecycle',
      role: 'assistant',
      content: '',
      isStreaming: true,
      timestamp: '2026-10-01T00:00:00Z'
    };

    const { rerender } = render(<ChatMessageItem message={latencyMsg} onRegenerate={handleRegenerate} />);

    // State 1 Assertions:
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Planning clinical navigation...');
    expect(screen.getByTestId('thinking-dots')).toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
    expect(screen.queryByTestId('message-copy-btn')).not.toBeInTheDocument();
    expect(screen.queryByTestId('message-rerun-btn')).not.toBeInTheDocument();

    // State 2: First token arrives (isStreaming=true, content='Based on your')
    const tokenStreamingMsg: ChatMessage = {
      ...latencyMsg,
      content: 'Based on your recent visit, '
    };

    rerender(<ChatMessageItem message={tokenStreamingMsg} onRegenerate={handleRegenerate} />);

    // State 2 Assertions:
    expect(screen.queryByTestId('thinking-indicator')).not.toBeInTheDocument();
    expect(screen.getByText(/Based on your recent visit,/)).toBeInTheDocument();
    const streamingCursor = screen.getByTestId('streaming-indicator');
    expect(streamingCursor).toBeInTheDocument();
    expect(streamingCursor.className).toContain('animate-pulse');
    expect(streamingCursor.className).toContain('bg-emerald-600');
    expect(streamingCursor.className).toContain('dark:bg-emerald-400');
    expect(screen.queryByTestId('message-copy-btn')).not.toBeInTheDocument();
    expect(screen.queryByTestId('message-rerun-btn')).not.toBeInTheDocument();

    // State 3: Stream finishes (isStreaming=false, content full text)
    const finishedMsg: ChatMessage = {
      ...latencyMsg,
      content: 'Based on your recent visit, you should schedule a 6-month follow-up.',
      isStreaming: false
    };

    rerender(<ChatMessageItem message={finishedMsg} onRegenerate={handleRegenerate} />);

    // State 3 Assertions:
    expect(screen.queryByTestId('thinking-indicator')).not.toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
    expect(screen.getByText(/Based on your recent visit, you should schedule a 6-month follow-up\./)).toBeInTheDocument();
    // Toolbar is now rendered
    expect(screen.getByTestId('message-copy-btn')).toBeInTheDocument();
    const regenBtn = screen.getByTestId('message-rerun-btn');
    expect(regenBtn).toBeInTheDocument();
    expect(regenBtn).toHaveAttribute('data-action', 'regenerate');
  });

  // ---------------------------------------------------------------------------
  // 2. DYNAMIC STATUS TEXT DURING ACTIVE TOOL EXECUTION
  // ---------------------------------------------------------------------------
  it('switches thinking text to "Executing clinical tools..." when running tools exist, and reverts to "Planning clinical navigation..." on completion', () => {
    const runningToolTrace: ToolTraceItem = {
      id: 'trace-1',
      tool: 'extract_document_dossier',
      status: 'running',
      input: { file_path: 'attachments/records.pdf' }
    };

    const msgWithRunningTool: ChatMessage = {
      id: 'msg-tool-stream',
      role: 'assistant',
      content: '',
      isStreaming: true,
      toolTraces: [runningToolTrace]
    };

    const { rerender } = render(<ChatMessageItem message={msgWithRunningTool} />);

    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Executing clinical tools...');

    // Tool completes before tokens arrive
    const completedToolTrace: ToolTraceItem = {
      ...runningToolTrace,
      status: 'completed',
      output: { summary: 'Completed extraction' },
      duration_ms: 320
    };

    const msgWithCompletedTool: ChatMessage = {
      ...msgWithRunningTool,
      toolTraces: [completedToolTrace]
    };

    rerender(<ChatMessageItem message={msgWithCompletedTool} />);

    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Planning clinical navigation...');
  });

  // ---------------------------------------------------------------------------
  // 3. WHITESPACE STREAMING IMMUNITY
  // ---------------------------------------------------------------------------
  it('maintains ThinkingIndicator when stream outputs initial whitespace characters (spaces, newlines, tabs)', () => {
    const whitespaceMsg: ChatMessage = {
      id: 'msg-whitespace',
      role: 'assistant',
      content: '  \n\n  \t  ',
      isStreaming: true
    };

    render(<ChatMessageItem message={whitespaceMsg} />);

    // Since content.trim() is empty, ThinkingIndicator remains visible
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // 4. REFUSAL STREAMING STATE INTEGRITY
  // ---------------------------------------------------------------------------
  it('displays safety refusal styling and reason callout properly during and after streaming', () => {
    const refusalStreamingMsg: ChatMessage = {
      id: 'msg-refusal-stream',
      role: 'assistant',
      content: 'I am a wellness assistant, not a doctor. I cannot provide diagnostic prescriptions.',
      isStreaming: true,
      isRefusal: true,
      refusalReason: 'clinical_diagnosis'
    };

    const { rerender } = render(<ChatMessageItem message={refusalStreamingMsg} />);

    expect(screen.getByTestId('chat-message-refusal')).toBeInTheDocument();
    expect(screen.getByTestId('safe-refusal-badge')).toBeInTheDocument();
    expect(screen.getByTestId('refusal-reason-callout')).toHaveTextContent('Blocked Category: clinical_diagnosis');
    // Content is streaming so cursor is present
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
    // Toolbar absent during streaming
    expect(screen.queryByTestId('message-copy-btn')).not.toBeInTheDocument();

    // Stream ends
    rerender(<ChatMessageItem message={{ ...refusalStreamingMsg, isStreaming: false }} />);

    expect(screen.getByTestId('chat-message-refusal')).toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
    expect(screen.getByTestId('message-copy-btn')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // 5. USER MESSAGE IMMUNITY
  // ---------------------------------------------------------------------------
  it('ensures user messages never render ThinkingIndicator or streaming cursor even if isStreaming flag is passed', () => {
    const userMsg: ChatMessage = {
      id: 'user-msg',
      role: 'user',
      content: 'Can you summarize my visit?',
      isStreaming: true
    };

    render(<ChatMessageItem message={userMsg} />);

    expect(screen.getByTestId('chat-message-user')).toBeInTheDocument();
    expect(screen.queryByTestId('thinking-indicator')).not.toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
  });
});

describe('Stress Suite: ToolTraceCard Accordion & Layout Shift Bounds', () => {
  it('bounds parameters and output pre tags to max-h-40 (160px) with overflow-auto preventing layout shifts', () => {
    const hugeTrace: ToolTraceItem = {
      id: 'trace-huge',
      tool: 'clinical_history_lookup',
      status: 'completed',
      input: {
        query: 'comprehensive historical analysis',
        params: Array.from({ length: 50 }, (_, i) => `key_${i}: value_${i}`)
      },
      output: {
        records: Array.from({ length: 100 }, (_, i) => ({ id: i, diagnosis: `Condition ${i}` }))
      },
      duration_ms: 120
    };

    render(<ToolTraceCard trace={hugeTrace} defaultExpanded={true} />);

    const paramsPre = screen.getByTestId('tool-trace-params');
    expect(paramsPre.className).toContain('max-h-40');
    expect(paramsPre.className).toContain('overflow-auto');

    const outputPre = screen.getByTestId('tool-trace-output');
    expect(outputPre.className).toContain('max-h-40');
    expect(outputPre.className).toContain('overflow-auto');
  });

  it('renders all four status badges cleanly without invalid Tailwind v4 classes', () => {
    const statuses: Array<ToolTraceItem['status']> = ['running', 'completed', 'denied', 'failed'];

    for (const status of statuses) {
      const trace: ToolTraceItem = {
        id: `trace-${status}`,
        tool: `tool_${status}`,
        status,
        reason: status === 'denied' ? 'Policy restriction' : undefined,
        error: status === 'failed' ? 'Connection timeout' : undefined
      };

      const { container, unmount } = render(<ToolTraceCard trace={trace} defaultExpanded={true} />);
      const html = container.innerHTML;

      // Assert zero Tailwind v4 classes
      expect(html).not.toContain('shadow-xs');
      expect(html).not.toContain('shadow-2xs');
      expect(html).not.toContain('focus:outline-hidden');
      expect(html).not.toContain('backdrop-blur-xs');

      // Assert status badge exists
      const badge = screen.getByTestId('tool-trace-status-badge');
      expect(badge).toBeInTheDocument();

      unmount();
    }
  });

  it('auto-expands running tool trace and stays expanded or collapses smoothly on user toggle', () => {
    const runningTrace: ToolTraceItem = {
      id: 'trace-active',
      tool: 'extract_document_dossier',
      status: 'running',
      input: { path: 'attachments/visit.pdf' }
    };

    render(<ToolTraceCard trace={runningTrace} />);

    // Auto-expanded on mount because status is 'running'
    expect(screen.getByTestId('tool-trace-details')).toBeInTheDocument();

    // User clicks to collapse
    const toggleBtn = screen.getByRole('button');
    fireEvent.click(toggleBtn);
    expect(screen.queryByTestId('tool-trace-details')).not.toBeInTheDocument();

    // User clicks to expand again
    fireEvent.click(toggleBtn);
    expect(screen.getByTestId('tool-trace-details')).toBeInTheDocument();
  });
});

describe('Stress Suite: ScrollToBottomButton Edge Cases & Accessibility', () => {
  it('correctly manages aria-label, tabIndex, and entrance/exit classes across visible toggle', () => {
    const { rerender } = render(<ScrollToBottomButton visible={false} onClick={vi.fn()} unreadCount={0} />);

    const hiddenBtn = screen.getByTestId('scroll-to-bottom-btn');
    expect(hiddenBtn).toHaveAttribute('tabIndex', '-1');
    expect(hiddenBtn.parentElement).toHaveClass('opacity-0');
    expect(hiddenBtn.parentElement).toHaveClass('pointer-events-none');

    // Reveal
    rerender(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={5} />);
    const visibleBtn = screen.getByTestId('scroll-to-bottom-btn');
    expect(visibleBtn).toHaveAttribute('tabIndex', '0');
    expect(visibleBtn.parentElement).toHaveClass('opacity-100');
    expect(visibleBtn.parentElement).toHaveClass('pointer-events-auto');
    expect(visibleBtn).toHaveAttribute('aria-label', 'Scroll to bottom (5 unread)');
  });

  it('caps unread counter badge text at "99+" for extreme unread token counts (100, 500, 9999)', () => {
    const counts = [100, 500, 9999];

    for (const count of counts) {
      const { unmount } = render(<ScrollToBottomButton visible={true} onClick={vi.fn()} unreadCount={count} />);
      const badge = screen.getByTestId('unread-counter-badge');
      expect(badge).toHaveTextContent('99+');
      unmount();
    }
  });

  it('verifies touch target dimensions are at least 44px (meeting >=44px touch target requirement)', () => {
    render(<ScrollToBottomButton visible={true} onClick={vi.fn()} />);
    const btn = screen.getByTestId('scroll-to-bottom-btn');
    expect(btn.className).toContain('min-w-[44px]');
    expect(btn.className).toContain('min-h-[44px]');
  });
});

describe('Stress Suite: Full Chat Flow, Abort, Regenerate & Rerun', () => {
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

  it('stops active streaming via Stop button, re-enables textarea, and preserves partial tokens', async () => {
    let abortListenerTriggered = false;
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        const signal = options.signal as AbortSignal;
        signal.addEventListener('abort', () => {
          abortListenerTriggered = true;
        });

        const encoder = new TextEncoder();
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode('event: token\ndata: {"type":"token","delta":"Partial clinical observation..."}\n\n'));
            // Do not close; wait for abort
          }
        });
        return Promise.resolve(new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } }));
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i) as HTMLTextAreaElement;

    fireEvent.change(textarea, { target: { value: 'Explain my symptoms' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    // Wait for partial token to render and Stop button to appear
    await waitFor(() => {
      expect(screen.getByText(/Partial clinical observation\.\.\./)).toBeInTheDocument();
      expect(screen.getByTitle('Stop Generation')).toBeInTheDocument();
      expect(textarea).toBeDisabled();
    });

    // Click Stop button
    fireEvent.click(screen.getByTitle('Stop Generation'));

    // Assert fetch was aborted, textarea is re-enabled, and Send button is restored
    await waitFor(() => {
      expect(abortListenerTriggered).toBe(true);
      expect(textarea).not.toBeDisabled();
      expect(screen.getByTitle('Send Prompt')).toBeInTheDocument();
    });

    // Message toolbar is now visible on both user and assistant messages
    expect(screen.getAllByTestId('message-copy-btn').length).toBe(2);
  });

  it('triggers regenerate on assistant message, rolling back previous response and restarting stream', async () => {
    let callCount = 0;
    const mockFetch = vi.fn().mockImplementation((url) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        callCount++;
        const text = callCount === 1 ? 'First draft response' : 'Regenerated refined response';
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: text } },
            { event: 'done', data: { type: 'done', fullText: text } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);

    // Turn 1
    fireEvent.change(textarea, { target: { value: 'Initial question' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByText('First draft response')).toBeInTheDocument();
    });

    // Click regenerate button on assistant card
    const regenBtn = screen.getByTitle('Regenerate response');
    expect(regenBtn).toBeInTheDocument();
    fireEvent.click(regenBtn);

    // Turn 2: Regenerated response arrives
    await waitFor(() => {
      expect(screen.getByText('Regenerated refined response')).toBeInTheDocument();
    });
    expect(screen.queryByText('First draft response')).not.toBeInTheDocument();
    expect(callCount).toBe(2);
  });

  it('reruns prompt on user message toolbar click', async () => {
    let lastPrompt = '';
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        const body = JSON.parse(options.body);
        lastPrompt = body.prompt;
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: `Answer to: ${lastPrompt}` } },
            { event: 'done', data: { type: 'done', fullText: `Answer to: ${lastPrompt}` } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);
    const textarea = screen.getByPlaceholderText(/Message Visit Steward/i);

    // Initial send
    fireEvent.change(textarea, { target: { value: 'My rerun question' } });
    fireEvent.click(screen.getByTitle('Send Prompt'));

    await waitFor(() => {
      expect(screen.getByText('Answer to: My rerun question')).toBeInTheDocument();
    });

    // Click rerun button on user message card
    const rerunBtn = screen.getByTitle('Rerun prompt');
    expect(rerunBtn).toBeInTheDocument();
    fireEvent.click(rerunBtn);

    await waitFor(() => {
      expect(lastPrompt).toBe('My rerun question');
    });
  });

  it('sends starter prompt on click from empty state', async () => {
    let capturedPrompt = '';
    const mockFetch = vi.fn().mockImplementation((url, options) => {
      if ((url === '/api/chat' || url === '/api/v1/chat')) {
        const body = JSON.parse(options.body);
        capturedPrompt = body.prompt;
        return Promise.resolve(
          createMockSSEResponse([
            { event: 'token', data: { type: 'token', delta: 'Here is what you should ask...' } },
            { event: 'done', data: { type: 'done', fullText: 'Here is what you should ask...' } }
          ])
        );
      }
      return Promise.resolve(new Response('{}', { status: 200 }));
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<ChatClient initialAgents={mockAgents} />);

    // Starter chip from mockAgents: 'What should I ask my doctor?'
    const starterBtn = screen.getByRole('button', { name: /What should I ask my doctor\?/i });
    expect(starterBtn).toBeInTheDocument();
    fireEvent.click(starterBtn);

    await waitFor(() => {
      expect(capturedPrompt).toBe('What should I ask my doctor?');
      expect(screen.getByText('Here is what you should ask...')).toBeInTheDocument();
    });
  });
});

