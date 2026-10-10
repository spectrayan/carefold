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
import { ThemeProvider, useTheme, ThemeScript } from '@/components/ThemeProvider';
import {
  THEME_STORAGE_KEY,
  getStoredTheme
} from '@/lib/theme';
import { CodeBlock, normalizeLanguage, tokenizeCode } from '@/components/chat/CodeBlock';
import { MessageToolbar } from '@/components/chat/MessageToolbar';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import { ScrollToBottomButton } from '@/components/chat/ScrollToBottomButton';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';

// Test consumer for ThemeProvider hooks
function ThemeStressConsumer() {
  const { theme, resolvedTheme, setTheme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="active-theme">{theme}</span>
      <span data-testid="active-resolved">{resolvedTheme}</span>
      <button data-testid="stress-toggle" onClick={toggleTheme}>Toggle</button>
      <button data-testid="stress-set-light" onClick={() => setTheme('light')}>Light</button>
      <button data-testid="stress-set-dark" onClick={() => setTheme('dark')}>Dark</button>
      <button data-testid="stress-set-system" onClick={() => setTheme('system')}>System</button>
    </div>
  );
}

describe('Final E2E Acceptance & Robustness Stress Test Suite', () => {
  let isOsDark = false;
  let matchMediaListeners: Array<(e: any) => void> = [];

  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
    isOsDark = false;
    matchMediaListeners = [];

    if (typeof window !== 'undefined') {
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: isOsDark,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn().mockImplementation((event: string, cb: (e: any) => void) => {
          if (event === 'change') matchMediaListeners.push(cb);
        }),
        removeEventListener: vi.fn().mockImplementation((_event: string, cb: (e: any) => void) => {
          matchMediaListeners = matchMediaListeners.filter((l) => l !== cb);
        }),
        dispatchEvent: vi.fn()
      }));
    }
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    localStorage.clear();
    document.documentElement.className = '';
    document.documentElement.removeAttribute('data-theme');
  });

  // =========================================================================
  // 1. THEME TRANSITIONS, RAPID TOGGLES & STORAGE CORRUPTION RECOVERY
  // =========================================================================
  describe('1. Theme Transitions, Rapid Toggles & Storage Corruption', () => {
    it('survives rapid toggle burst (100 rapid toggles) maintaining strict deterministic state', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <ThemeStressConsumer />
        </ThemeProvider>
      );

      const toggleBtn = screen.getByTestId('stress-toggle');
      const activeTheme = screen.getByTestId('active-theme');
      const activeResolved = screen.getByTestId('active-resolved');

      expect(activeTheme).toHaveTextContent('light');
      expect(activeResolved).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);

      // Perform 100 rapid toggles in rapid succession
      for (let i = 1; i <= 100; i++) {
        act(() => {
          fireEvent.click(toggleBtn);
        });
        const expectedResolved = i % 2 === 1 ? 'dark' : 'light';
        expect(activeResolved).toHaveTextContent(expectedResolved);
        expect(document.documentElement.classList.contains('dark')).toBe(expectedResolved === 'dark');
        expect(document.documentElement.getAttribute('data-theme')).toBe(expectedResolved);
        expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(expectedResolved);
      }
    });

    it('gracefully degrades when localStorage.setItem throws QuotaExceededError or SecurityError', () => {
      const setItemSpy = vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
        const error = new DOMException('QuotaExceededError: The quota has been exceeded', 'QuotaExceededError');
        throw error;
      });

      render(
        <ThemeProvider defaultTheme="light">
          <ThemeStressConsumer />
        </ThemeProvider>
      );

      const toggleBtn = screen.getByTestId('stress-toggle');
      const activeResolved = screen.getByTestId('active-resolved');

      // Toggling should NOT crash even though localStorage throws
      expect(() => {
        act(() => {
          fireEvent.click(toggleBtn);
        });
      }).not.toThrow();

      expect(setItemSpy).toHaveBeenCalled();
      expect(activeResolved).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('recovers cleanly when localStorage.getItem throws SecurityError (sandboxed iframe / cookies blocked)', () => {
      vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
        throw new DOMException('SecurityError: The operation is insecure', 'SecurityError');
      });

      // getStoredTheme should not throw and return fallback
      expect(() => getStoredTheme('system')).not.toThrow();
      expect(getStoredTheme('system')).toBe('system');
      expect(getStoredTheme('dark')).toBe('dark');

      // ThemeProvider should mount without crashing
      const { unmount } = render(
        <ThemeProvider defaultTheme="light">
          <ThemeStressConsumer />
        </ThemeProvider>
      );

      expect(screen.getByTestId('active-theme')).toBeInTheDocument();
      unmount();
    });

    it('sanitizes malicious, malformed, and prototype pollution localStorage values', () => {
      const hostileValues = [
        '{"__proto__": {"admin": true}}',
        'constructor',
        'prototype',
        '<script>alert("xss")</script>',
        'DARK',
        'LIGHT',
        'SYSTEM',
        'auto',
        'null',
        'undefined',
        '0',
        '1',
        'false',
        'true',
        'NaN',
        '["dark"]',
        'dark; DROP TABLE users;',
        '   light   '
      ];

      for (const val of hostileValues) {
        localStorage.setItem(THEME_STORAGE_KEY, val);
        const resolvedStored = getStoredTheme('system');
        // Must reject all corrupted or non-exact enum values and fallback to default
        expect(resolvedStored).toBe('system');
      }
    });

    it('resiliently handles OS system theme preference changes and media listener lifecycle', () => {
      isOsDark = false;
      render(
        <ThemeProvider defaultTheme="system">
          <ThemeStressConsumer />
        </ThemeProvider>
      );

      expect(screen.getByTestId('active-theme')).toHaveTextContent('system');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
      expect(document.documentElement.classList.contains('dark')).toBe(false);

      // Simulate OS switching to Dark Mode
      act(() => {
        isOsDark = true;
        matchMediaListeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent));
      });

      expect(screen.getByTestId('active-resolved')).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);

      // Explicitly set theme to 'light' -> OS changes should now be ignored
      act(() => {
        fireEvent.click(screen.getByTestId('stress-set-light'));
      });
      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');

      // OS switches back to Light, then back to Dark
      act(() => {
        isOsDark = true;
        matchMediaListeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent));
      });
      // Remains light because user explicitly chose light
      expect(screen.getByTestId('active-resolved')).toHaveTextContent('light');
    });

    it('handles cross-tab StorageEvent storms including malformed and unrelated events', () => {
      render(
        <ThemeProvider defaultTheme="light">
          <ThemeStressConsumer />
        </ThemeProvider>
      );

      // Unrelated key should not alter theme
      act(() => {
        window.dispatchEvent(new StorageEvent('storage', {
          key: 'some_other_key',
          newValue: 'dark'
        }));
      });
      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');

      // Corrupted value for carefold_theme should be ignored
      act(() => {
        window.dispatchEvent(new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: 'CORRUPTED_VALUE'
        }));
      });
      expect(screen.getByTestId('active-theme')).toHaveTextContent('light');

      // Legitimate cross-tab theme update to 'dark'
      act(() => {
        window.dispatchEvent(new StorageEvent('storage', {
          key: THEME_STORAGE_KEY,
          newValue: 'dark'
        }));
      });
      expect(screen.getByTestId('active-theme')).toHaveTextContent('dark');
      expect(document.documentElement.classList.contains('dark')).toBe(true);
    });

    it('ThemeScript renders safely and executes without uncaught errors in restricted environments', () => {
      const { container } = render(<ThemeScript />);
      const script = container.querySelector('script');
      expect(script).not.toBeNull();
      const code = script?.innerHTML || '';
      expect(code).toContain(THEME_STORAGE_KEY);
      expect(code).toContain('try {');
      expect(code).toContain('} catch (e) {}');
    });
  });

  // =========================================================================
  // 2. CODE BLOCK TOKENIZER & EDGE CASES
  // =========================================================================
  describe('2. Code Block Tokenizer & Syntax Edge Cases', () => {
    it('handles empty, whitespace-only, and massive single-line inputs without ReDoS', () => {
      expect(tokenizeCode('', 'python')).toEqual([]);
      expect(tokenizeCode('   \n\t  ', 'text')).toEqual([{ type: 'plain', text: '   \n\t  ' }]);

      // 20,000 character single line string
      const hugeLine = 'a = "' + 'x'.repeat(20000) + '";\n';
      const t0 = performance.now();
      const tokens = tokenizeCode(hugeLine, 'javascript');
      const elapsed = performance.now() - t0;

      expect(elapsed).toBeLessThan(500); // Must be fast, no catastrophic backtracking
      expect(tokens.length).toBeGreaterThan(0);
    });

    it('tokenizes multi-language syntax accurately: Python, JS/TS, Bash, SQL, JSON, YAML', () => {
      // Python
      const pyCode = 'async def fetch_data(user_id: int = 42):\n    # Clinical comment\n    return "ok"';
      const pyTokens = tokenizeCode(pyCode, 'py');
      expect(pyTokens.some((t) => t.type === 'keyword' && t.text === 'async')).toBe(true);
      expect(pyTokens.some((t) => t.type === 'keyword' && t.text === 'def')).toBe(true);
      expect(pyTokens.some((t) => t.type === 'comment' && t.text.includes('Clinical comment'))).toBe(true);
      expect(pyTokens.some((t) => t.type === 'string' && t.text === '"ok"')).toBe(true);

      // Bash
      const bashCode = 'if [ -f "$FILE" ]; then\n  curl -s https://api.carefold.com\nfi # check';
      const bashTokens = tokenizeCode(bashCode, 'bash');
      expect(bashTokens.some((t) => t.type === 'keyword' && t.text === 'if')).toBe(true);
      expect(bashTokens.some((t) => t.type === 'keyword' && t.text === 'curl')).toBe(true);

      // SQL
      const sqlCode = 'SELECT id, copay FROM claims WHERE status = "APPROVED";';
      const sqlTokens = tokenizeCode(sqlCode, 'sql');
      expect(sqlTokens.some((t) => t.type === 'keyword' && t.text === 'SELECT')).toBe(true);
      expect(sqlTokens.some((t) => t.type === 'keyword' && t.text === 'WHERE')).toBe(true);

      // JSON properties
      const jsonCode = '{\n  "patient_name": "Jane Doe",\n  "age": 35\n}';
      const jsonTokens = tokenizeCode(jsonCode, 'json');
      expect(jsonTokens.some((t) => t.type === 'property' && t.text === '"patient_name"')).toBe(true);
      expect(jsonTokens.some((t) => t.type === 'number' && t.text === '35')).toBe(true);
    });

    it('neutralizes XSS and HTML injection attempts inside code blocks', () => {
      const maliciousCode = '<script>window.pwned = true;</script><img src=x onerror="alert(1)">';
      render(<CodeBlock code={maliciousCode} language="html" />);

      // The text must be present as plain string content, not as active DOM elements
      expect(screen.getByTestId('code-block')).toHaveTextContent('<script>window.pwned = true;</script>');
      expect(document.querySelector('img[src="x"]')).toBeNull();
      expect((window as any).pwned).toBeUndefined();
    });

    it('normalizes arbitrary and exotic language strings without crashing', () => {
      const exotic = [
        'C++',
        'C#',
        'F#',
        'Rust',
        'GoLang',
        'COBOL',
        'brainfuck',
        '"><svg onload=alert(1)>',
        'python 3.11 with args',
        '  typescript  '
      ];

      for (const lang of exotic) {
        expect(() => normalizeLanguage(lang)).not.toThrow();
        const norm = normalizeLanguage(lang);
        expect(typeof norm).toBe('string');
        expect(norm.length).toBeGreaterThan(0);
        expect(() => tokenizeCode('test code', lang)).not.toThrow();
      }
    });

    it('renders unclosed code block during active SSE streaming in ChatMessageItem', () => {
      const streamingMsg: ChatMessage = {
        id: 'msg-stream-code',
        role: 'assistant',
        content: 'Analyzing records:\n```json\n{\n  "status": "pending"',
        isStreaming: true
      };

      render(<ChatMessageItem message={streamingMsg} />);
      expect(screen.getByTestId('code-block')).toBeInTheDocument();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('json');
      expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
    });
  });

  // =========================================================================
  // 3. CLIPBOARD ERROR HANDLING, DEBOUNCE & EXECCOMMAND FALLBACK
  // =========================================================================
  describe('3. Clipboard Error Handling, Debounce & execCommand Fallback', () => {
    it('debounces rapid spam clicks on CodeBlock copy button and resets 2000ms timer', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      render(<CodeBlock code="const a = 10;" language="javascript" />);

      const copyBtn = screen.getByTestId('copy-code-btn');

      // Click 1
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(1);
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Advance 1000ms
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Click 2 (spam click resets timer)
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(writeTextSpy).toHaveBeenCalledTimes(2);

      // Advance 1500ms (total 2500ms; would have expired if not reset)
      act(() => {
        vi.advanceTimersByTime(1500);
      });
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      // Advance another 600ms (total 3100ms, >2000ms after 2nd click)
      act(() => {
        vi.advanceTimersByTime(600);
      });
      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
    });

    it('debounces rapid spam clicks on MessageToolbar copy button and resets 2000ms timer', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      render(
        <MessageToolbar
          role="assistant"
          content="Copyable clinical advice"
          messageId="msg-toolbar-1"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');

      // Rapid burst of 5 clicks
      for (let i = 1; i <= 5; i++) {
        await act(async () => {
          fireEvent.click(copyBtn);
        });
        expect(writeTextSpy).toHaveBeenCalledTimes(i);
        expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();
      }

      // Advance 1500ms
      act(() => {
        vi.advanceTimersByTime(1500);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Advance another 1000ms
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();
    });

    it('handles clipboard writeText rejection (NotAllowedError/SecurityError) gracefully without UI break', async () => {
      vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(
        new DOMException('Permission denied', 'NotAllowedError')
      );

      render(<CodeBlock code="sensitive medical data" language="text" />);
      const copyBtn = screen.getByTestId('copy-code-btn');

      // Should not throw an unhandled rejection
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      // Copied checkmark must NOT appear on error
      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
      expect(copyBtn).toHaveAttribute('aria-label', 'Copy code');
    });

    it('falls back seamlessly to document.execCommand when navigator.clipboard is unavailable', async () => {
      const originalClipboard = navigator.clipboard;
      // Simulate insecure context or older browser without navigator.clipboard
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      const execMock = vi.fn().mockReturnValue(true);
      (document as any).execCommand = execMock;

      render(
        <MessageToolbar
          role="user"
          content="Prompt to copy via execCommand"
          messageId="user-msg-exec"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');
      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(execMock).toHaveBeenCalledWith('copy');
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Reverts after 2000ms
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(screen.queryByTestId('message-copy-success')).not.toBeInTheDocument();

      // Restore clipboard
      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
      delete (document as any).execCommand;
    });

    it('handles document.execCommand throwing an error gracefully without crash', async () => {
      const originalClipboard = navigator.clipboard;
      Object.defineProperty(navigator, 'clipboard', {
        value: undefined,
        configurable: true,
        writable: true
      });

      (document as any).execCommand = vi.fn().mockImplementation(() => {
        throw new Error('execCommand is disabled by document policy');
      });

      render(<CodeBlock code="code fallback test" language="text" />);
      const copyBtn = screen.getByTestId('copy-code-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();

      Object.defineProperty(navigator, 'clipboard', {
        value: originalClipboard,
        configurable: true,
        writable: true
      });
      delete (document as any).execCommand;
    });

    it('cleans up timeout timers on component unmount to prevent leaks and setState on unmounted components', async () => {
      vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      const { unmount } = render(
        <MessageToolbar
          role="assistant"
          content="Temporary message"
          messageId="temp-msg-1"
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');
      await act(async () => {
        fireEvent.click(copyBtn);
      });
      expect(screen.getByTestId('message-copy-success')).toBeInTheDocument();

      // Unmount before 2000ms expires
      unmount();

      // Advancing timer after unmount should not cause warnings or errors
      expect(() => {
        act(() => {
          vi.advanceTimersByTime(2500);
        });
      }).not.toThrow();
    });
  });

  // =========================================================================
  // 4. ACTION TOOLBAR, THINKING INDICATOR & SCROLL TO BOTTOM
  // =========================================================================
  describe('4. Action Toolbar, Thinking Indicator & Scroll UX Stress Tests', () => {
    it('handles user rerun action and assistant regenerate action triggers', () => {
      const rerunSpy = vi.fn();
      const regenerateSpy = vi.fn();

      // User Message with Rerun
      const { unmount: unmountUser } = render(
        <ChatMessageItem
          message={{
            id: 'msg-u1',
            role: 'user',
            content: 'Find in-network cardiologist'
          }}
          onRerun={rerunSpy}
        />
      );

      const rerunBtn = screen.getByTestId('message-rerun-btn');
      expect(rerunBtn).toHaveAttribute('data-action', 'rerun');
      fireEvent.click(rerunBtn);
      expect(rerunSpy).toHaveBeenCalledWith('Find in-network cardiologist');
      unmountUser();

      // Assistant Message with Regenerate
      render(
        <ChatMessageItem
          message={{
            id: 'msg-a1',
            role: 'assistant',
            content: 'Here are 3 cardiologist options.'
          }}
          onRegenerate={regenerateSpy}
        />
      );

      const regenBtn = screen.getByTestId('message-rerun-btn');
      expect(regenBtn).toHaveAttribute('data-action', 'regenerate');
      fireEvent.click(regenBtn);
      expect(regenerateSpy).toHaveBeenCalledWith('msg-a1');
    });

    it('disables regenerate button when assistant message is actively streaming', () => {
      const regenerateSpy = vi.fn();
      render(
        <ChatMessageItem
          message={{
            id: 'msg-streaming',
            role: 'assistant',
            content: 'Partially generated...',
            isStreaming: true
          }}
          onRegenerate={regenerateSpy}
        />
      );

      // During active streaming, action toolbar is hidden or disabled to prevent race conditions
      expect(screen.queryByTestId('message-rerun-btn')).toBeNull();
    });

    it('renders ThinkingIndicator with animated dots and custom planning/tool status', () => {
      const { rerender } = render(<ThinkingIndicator text="Planning clinical navigation..." />);
      expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
      expect(screen.getByTestId('thinking-dots')).toBeInTheDocument();
      expect(screen.getByTestId('thinking-text')).toHaveTextContent('Planning clinical navigation...');

      rerender(<ThinkingIndicator text="Executing clinical tools..." />);
      expect(screen.getByTestId('thinking-text')).toHaveTextContent('Executing clinical tools...');
    });

    it('ScrollToBottomButton reflects visibility and formats unread counts accurately (>99 -> 99+)', () => {
      const clickSpy = vi.fn();
      const { rerender } = render(
        <ScrollToBottomButton visible={false} onClick={clickSpy} unreadCount={0} />
      );

      // Invisible state has opacity-0 and pointer-events-none
      const btn = screen.getByTestId('scroll-to-bottom-btn');
      expect(btn.parentElement).toHaveClass('opacity-0');
      expect(screen.queryByTestId('unread-counter-badge')).toBeNull();

      // Scrolled away with 5 unread items
      rerender(<ScrollToBottomButton visible={true} onClick={clickSpy} unreadCount={5} />);
      expect(btn.parentElement).toHaveClass('opacity-100');
      const badge5 = screen.getByTestId('unread-counter-badge');
      expect(badge5).toHaveTextContent('5');

      // Overflow count: 120 unread -> displays '99+'
      rerender(<ScrollToBottomButton visible={true} onClick={clickSpy} unreadCount={120} />);
      const badgeOverflow = screen.getByTestId('unread-counter-badge');
      expect(badgeOverflow).toHaveTextContent('99+');

      // Clicking calls onClick
      fireEvent.click(btn);
      expect(clickSpy).toHaveBeenCalledTimes(1);
    });
  });
});
