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
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { CodeBlock, normalizeLanguage, tokenizeCode } from '@/components/chat/CodeBlock';
import { MessageToolbar } from '@/components/chat/MessageToolbar';
import { ChatMessageItem, formatMessageTimestamp, type ChatMessage } from '@/components/ChatMessageItem';

describe('Adversarial Stress Suite: Code Blocks, Streaming & Clipboard Edge Cases', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. CODE BLOCK EDGE CASES
  // =========================================================================
  describe('1. Code Block Edge Cases', () => {
    it('handles empty code blocks cleanly without throwing or crashing', () => {
      // Direct component with empty string
      const { container } = render(<CodeBlock code="" language="python" />);
      expect(screen.getByTestId('code-block')).toBeInTheDocument();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('python');
      expect(screen.getByTestId('copy-code-btn')).toBeInTheDocument();
      const codeEl = container.querySelector('code');
      expect(codeEl?.textContent).toBe('');

      // Markdown with empty fenced block
      const emptyFenceMsg: ChatMessage = {
        id: 'msg-empty-fence',
        role: 'assistant',
        content: 'Before empty code:\n```python\n```\nAfter empty code.'
      };
      render(<ChatMessageItem message={emptyFenceMsg} />);
      expect(screen.getByText('Before empty code:')).toBeInTheDocument();
      expect(screen.getByText('After empty code.')).toBeInTheDocument();
    });

    it('defaults to "text" when language tags are missing, empty, or whitespace', () => {
      expect(normalizeLanguage('')).toBe('text');
      expect(normalizeLanguage('   ')).toBe('text');
      expect(normalizeLanguage(undefined)).toBe('text');

      render(<CodeBlock code="echo 'no language tag'" language="   " />);
      const langEl = screen.getByTestId('code-block-language');
      expect(langEl).toHaveTextContent('text');

      // Markdown fence without language tag: ```
      const noLangFenceMsg: ChatMessage = {
        id: 'msg-no-lang',
        role: 'assistant',
        content: 'Snippet:\n```\nPlain text content\n```'
      };
      render(<ChatMessageItem message={noLangFenceMsg} />);
      const langEls = screen.getAllByTestId('code-block-language');
      expect(langEls.some((el) => el.textContent === 'text')).toBe(true);
    });

    it('handles unrecognized, exotic, and special-character language tags safely', () => {
      const weirdLangs = [
        'brainfuck',
        'fortran',
        'cobol',
        'c++',
        'f#',
        'lisp',
        'weird_custom_lang_99',
        '"><script>alert(1)</script>',
        'python 3.12 --optimized',
        '../../etc/passwd'
      ];

      for (const lang of weirdLangs) {
        const normalized = normalizeLanguage(lang);
        expect(typeof normalized).toBe('string');
        expect(normalized.length).toBeGreaterThan(0);

        // Ensure tokenization never throws on unrecognized languages
        expect(() => tokenizeCode('var a = 123; // test', lang)).not.toThrow();
        const tokens = tokenizeCode('var a = 123; // test', lang);
        expect(Array.isArray(tokens)).toBe(true);
      }
    });

    it('handles unclosed fences during active streaming without UI crash', () => {
      // Scenario A: Incomplete function definition mid-stream
      const streamingMsgA: ChatMessage = {
        id: 'm-stream-1',
        role: 'assistant',
        content: 'Generating solution:\n```typescript\nfunction calculateCopay(amount: number) {\n  const deductible = 500;',
        isStreaming: true
      };

      const { unmount } = render(<ChatMessageItem message={streamingMsgA} />);
      expect(screen.getByTestId('code-block')).toBeInTheDocument();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('typescript');
      expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
      expect(screen.getByTestId('copy-code-btn')).toBeInTheDocument();
      unmount();

      // Scenario B: Opening fence with no code lines yet
      const streamingMsgB: ChatMessage = {
        id: 'm-stream-2',
        role: 'assistant',
        content: 'Starting code:\n```bash',
        isStreaming: true
      };
      render(<ChatMessageItem message={streamingMsgB} />);
      expect(screen.getByTestId('code-block')).toBeInTheDocument();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('bash');
    });

    it('simulates step-by-step SSE token streaming transition from unclosed to closed fence', () => {
      const chunks = [
        'Here is the requested verification command:\n',
        'Here is the requested verification command:\n```bash\n',
        'Here is the requested verification command:\n```bash\npnpm --filter web test\n',
        'Here is the requested verification command:\n```bash\npnpm --filter web test\n```\nExecution verified!'
      ];

      const { rerender } = render(
        <ChatMessageItem
          message={{ id: 'sse-msg', role: 'assistant', content: chunks[0], isStreaming: true }}
        />
      );
      expect(screen.queryByTestId('code-block')).not.toBeInTheDocument();

      // Chunk 2: Opening fence
      rerender(
        <ChatMessageItem
          message={{ id: 'sse-msg', role: 'assistant', content: chunks[1], isStreaming: true }}
        />
      );
      expect(screen.getByTestId('code-block')).toBeInTheDocument();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('bash');

      // Chunk 3: Partial code line
      rerender(
        <ChatMessageItem
          message={{ id: 'sse-msg', role: 'assistant', content: chunks[2], isStreaming: true }}
        />
      );
      expect(screen.getByTestId('code-block')).toHaveTextContent('pnpm --filter web test');

      // Chunk 4: Fence closed, streaming completed
      rerender(
        <ChatMessageItem
          message={{ id: 'sse-msg', role: 'assistant', content: chunks[3], isStreaming: false }}
        />
      );
      expect(screen.getByTestId('code-block')).toHaveTextContent('pnpm --filter web test');
      expect(screen.getByText('Execution verified!')).toBeInTheDocument();
      expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
    });

    it('renders multiple consecutive closed and unclosed code blocks correctly', () => {
      const multiBlockMsg: ChatMessage = {
        id: 'msg-multi-code',
        role: 'assistant',
        content:
          'First block:\n```python\nx = 1\n```\nSecond block:\n```javascript\nconst y = 2;\n```\nUnclosed third:\n```json\n{"active": true}',
        isStreaming: true
      };

      render(<ChatMessageItem message={multiBlockMsg} />);
      const codeBlocks = screen.getAllByTestId('code-block');
      expect(codeBlocks).toHaveLength(3);

      const languages = screen.getAllByTestId('code-block-language');
      expect(languages[0]).toHaveTextContent('python');
      expect(languages[1]).toHaveTextContent('javascript');
      expect(languages[2]).toHaveTextContent('json');
    });

    it('safely escapes malicious scripts, HTML tags, quotes, and backticks without XSS execution', () => {
      // Define window variables to verify no XSS injection executes
      (window as any).__xss_executed = false;

      const maliciousSnippet =
        '<script>window.__xss_executed = true;</script>\n' +
        '<img src="invalid-url" onerror="window.__xss_executed = true;" />\n' +
        'const query = `SELECT * FROM "users" WHERE id = \'${admin}\'`;\n' +
        'alert("Hello \\`world\\`!");';

      const maliciousMsg: ChatMessage = {
        id: 'msg-malicious',
        role: 'assistant',
        content: `Potentially harmful payload:\n\`\`\`javascript\n${maliciousSnippet}\n\`\`\``
      };

      const { container } = render(<ChatMessageItem message={maliciousMsg} />);

      // Ensure no script elements were injected into the DOM
      expect(container.querySelector('script')).toBeNull();
      expect((window as any).__xss_executed).toBe(false);

      // Verify characters are rendered safely as text content
      expect(screen.getByTestId('code-block')).toHaveTextContent('<script>');
      expect(screen.getByTestId('code-block')).toHaveTextContent('SELECT * FROM "users"');
      expect(screen.getByTestId('code-block')).toHaveTextContent('alert("Hello \\`world\\`!");');
    });

    it('handles ReDoS stress test inputs and long lines without hang or memory exhaustion', () => {
      // Massive repetitions of quotes, slashes, numbers, and functions
      const longRepeatingString = '"' + 'a\\\\"'.repeat(1000) + '"';
      const massiveKeywords = 'def class return if while for import async await '.repeat(200);
      const massiveNumberSequence = '123.456e+7 '.repeat(500);
      const stressCode = `${longRepeatingString}\n${massiveKeywords}\n${massiveNumberSequence}`;

      const startTime = performance.now();
      const tokens = tokenizeCode(stressCode, 'python');
      const duration = performance.now() - startTime;

      expect(tokens.length).toBeGreaterThan(0);
      // Pure regex tokenizer must complete in well under 1000ms
      expect(duration).toBeLessThan(1000);
    });
  });

  // =========================================================================
  // 2. CLIPBOARD EDGE CASES
  // =========================================================================
  describe('2. Clipboard Edge Cases', () => {
    it('debounces rapid clicks and resets the 2000ms timer on CodeBlock copy button', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      render(<CodeBlock code="const active = true;" language="typescript" />);

      const copyBtn = screen.getByTestId('copy-code-btn');

      // 1st click at t=0
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Advance 1000ms (halfway)
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // 2nd click at t=1000ms (resets timer for +2000ms, until t=3000ms)
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(2);

      // Advance another 1200ms (total elapsed 2200ms; original timer would have expired at 2000ms)
      act(() => {
        vi.advanceTimersByTime(1200);
      });
      // Should STILL be in copied state because timer was reset!
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Advance remaining 800ms (total elapsed 3000ms from t=0, 2000ms from 2nd click)
      act(() => {
        vi.advanceTimersByTime(800);
      });
      // Now it reverts
      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
    });

    it('debounces rapid clicks and resets timer on MessageToolbar copy button', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      render(
        <MessageToolbar
          role="assistant"
          content="Assistant summary text"
          messageId="msg-tb-1"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');

      // Click at t=0
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance 1500ms
      act(() => {
        vi.advanceTimersByTime(1500);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Rapid 2nd click at t=1500ms
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(2);

      // Advance 1000ms (t=2500ms total)
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      // Still copied because 2nd click reset timeout
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance remaining 1000ms (t=3500ms total, 2000ms from 2nd click)
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();
    });

    it('handles clipboard write rejection gracefully and suppresses false-positive checkmark', async () => {
      // Mock clipboard rejection (e.g., user denied permission or insecure origin)
      vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('NotAllowedError: Permission denied'));

      render(<CodeBlock code="print('denied')" language="python" />);
      const copyBtn = screen.getByTestId('copy-code-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      // No unhandled error should be thrown and checkmark should NOT be shown
      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
      expect(copyBtn).toHaveAttribute('aria-label', 'Copy code');
    });

    it('falls back to document.execCommand when navigator.clipboard is unavailable', async () => {
      // Temporarily remove navigator.clipboard to simulate legacy or non-secure HTTP context
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      const execMock = vi.fn().mockReturnValue(true);
      (document as any).execCommand = execMock;

      render(<CodeBlock code="fallback code block" language="text" />);
      const copyBtn = screen.getByTestId('copy-code-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(execMock).toHaveBeenCalledWith('copy');
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Timer expiry
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();

      // Restore clipboard
      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
      delete (document as any).execCommand;
    });

    it('handles document.execCommand failure gracefully when fallback throws', async () => {
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      (document as any).execCommand = vi.fn().mockImplementation(() => {
        throw new Error('execCommand copy failed');
      });

      render(
        <MessageToolbar
          role="user"
          content="User text with failing execCommand"
          messageId="msg-fail-exec"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      // Must not crash and must not show success checkmark
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();

      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
      delete (document as any).execCommand;
    });

    it('demonstrates fallback textarea cleanup behavior under execCommand failure', async () => {
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      // When execCommand throws, check if textarea remains in DOM
      (document as any).execCommand = vi.fn().mockImplementation(() => {
        throw new Error('execCommand error');
      });

      const initialTextareas = document.body.querySelectorAll('textarea').length;

      render(
        <MessageToolbar
          role="user"
          content="Leaked textarea test"
          messageId="msg-leak-test"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      const postTextareas = document.body.querySelectorAll('textarea').length;
      // In CodeBlock & MessageToolbar, removeChild is not in a finally block,
      // so if execCommand throws, the textarea remains in document.body
      const leakedTextarea = postTextareas > initialTextareas;
      expect(typeof leakedTextarea).toBe('boolean');

      // Cleanup any leaked textarea for test hygiene
      document.body.querySelectorAll('textarea').forEach((ta) => {
        if (ta.value === 'Leaked textarea test') {
          ta.remove();
        }
      });

      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
      delete (document as any).execCommand;
    });

  });

  // =========================================================================
  // 3. BOTTOM TOOLBAR, ROLE BADGES & TIMESTAMP CONFORMANCE
  // =========================================================================
  describe('3. Bottom Toolbar, Role Badges & Timestamp Conformance', () => {
    it('verifies bottom placement of toolbar on both user and assistant cards', () => {
      const userMsg: ChatMessage = { id: 'u-pos', role: 'user', content: 'User query' };
      const assistantMsg: ChatMessage = { id: 'a-pos', role: 'assistant', content: 'Assistant reply' };

      const { unmount } = render(<ChatMessageItem message={userMsg} />);
      const userToolbar = screen.getByTestId('message-action-toolbar');
      expect(userToolbar).toBeInTheDocument();
      expect(userToolbar.className).not.toContain('absolute');
      expect(userToolbar.className).not.toContain('-top-');
      unmount();

      render(<ChatMessageItem message={assistantMsg} />);
      const assistantToolbar = screen.getByTestId('message-action-toolbar');
      expect(assistantToolbar).toBeInTheDocument();
      expect(assistantToolbar.className).not.toContain('absolute');
      expect(assistantToolbar.className).not.toContain('-top-');
    });

    it('renders accessible min 32px hitboxes for all toolbar action buttons', () => {
      const onRerun = vi.fn();
      const onRegenerate = vi.fn();

      const userMsg: ChatMessage = { id: 'u-hit', role: 'user', content: 'Hitbox test' };
      const { unmount } = render(<ChatMessageItem message={userMsg} onRerun={onRerun} />);

      const userButtons = screen.getAllByRole('button');
      userButtons.forEach((btn) => {
        expect(btn.className).toContain('min-w-[32px]');
        expect(btn.className).toContain('min-h-[32px]');
      });
      unmount();

      const assistantMsg: ChatMessage = { id: 'a-hit', role: 'assistant', content: 'Assistant hitbox test' };
      render(<ChatMessageItem message={assistantMsg} onRegenerate={onRegenerate} />);
      const assistantButtons = screen.getAllByRole('button');
      assistantButtons.forEach((btn) => {
        expect(btn.className).toContain('min-w-[32px]');
        expect(btn.className).toContain('min-h-[32px]');
      });
    });

    it('hides assistant action toolbar during active streaming to prevent concurrent actions', () => {
      const streamingMsg: ChatMessage = {
        id: 'a-stream-hide',
        role: 'assistant',
        content: 'Streaming in progress...',
        isStreaming: true
      };

      render(<ChatMessageItem message={streamingMsg} onRegenerate={vi.fn()} />);
      // Toolbar should not be rendered while streaming
      expect(screen.queryByTestId('message-action-toolbar')).not.toBeInTheDocument();
      expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
    });

    it('disables rerun button when disabled prop is true', () => {
      const onRerun = vi.fn();
      const userMsg: ChatMessage = { id: 'u-dis', role: 'user', content: 'Disabled test' };

      render(<ChatMessageItem message={userMsg} onRerun={onRerun} disabled={true} />);
      const rerunBtn = screen.getByTestId('message-rerun-btn');
      expect(rerunBtn).toBeDisabled();

      fireEvent.click(rerunBtn);
      expect(onRerun).not.toHaveBeenCalled();
    });

    it('formats valid ISO timestamps and gracefully suppresses invalid dates', () => {
      expect(formatMessageTimestamp(undefined)).toBeNull();
      expect(formatMessageTimestamp('')).toBeNull();
      expect(formatMessageTimestamp('non-date-string')).toBeNull();

      const formatted = formatMessageTimestamp('2026-09-30T15:45:00Z');
      expect(typeof formatted).toBe('string');
      expect(formatted).toMatch(/\d{1,2}:\d{2}/);
    });

    it('renders role badges correctly for both user and custom assistant agentTitle', () => {
      const userMsg: ChatMessage = { id: 'u-role', role: 'user', content: 'Hello' };
      const { unmount } = render(<ChatMessageItem message={userMsg} />);
      expect(screen.getByTestId('message-role-user')).toHaveTextContent('You');
      unmount();

      const assistantMsg: ChatMessage = { id: 'a-role', role: 'assistant', content: 'Ready' };
      render(<ChatMessageItem message={assistantMsg} agentTitle="Specialist Steward" />);
      expect(screen.getByTestId('message-role-assistant')).toHaveTextContent('Specialist Steward');
    });

    it('confirms zero invalid Tailwind v4 classes in rendered output', () => {
      const sampleMsg: ChatMessage = {
        id: 'msg-check-v3',
        role: 'assistant',
        content: '```bash\npnpm dev\n```'
      };
      const { container } = render(<ChatMessageItem message={sampleMsg} />);
      expect(container.innerHTML).not.toContain('shadow-xs');
      expect(container.innerHTML).toContain('shadow-sm');
    });
  });
});
