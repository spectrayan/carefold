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
import fs from 'fs';
import path from 'path';
import { ChatMessageItem, type ChatMessage, formatMessageTimestamp } from '@/components/ChatMessageItem';
import { MessageToolbar } from '@/components/chat/MessageToolbar';
import { CodeBlock, normalizeLanguage, tokenizeCode } from '@/components/chat/CodeBlock';
import { SAFE_REFUSAL_TEMPLATE } from '@/types/api';

describe('Adversarial Challenge: Layout, Toolbars & Code Blocks', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // ===========================================================================
  // Dimension 1: Layout & Mobile Responsiveness (No Clipping, Bottom Placement)
  // ===========================================================================
  describe('Dimension 1: Layout Placement & Scroll Container Isolation', () => {
    it('renders toolbar inside the bottom border-t footer row, strictly never as absolute floating', () => {
      const userMsg: ChatMessage = {
        id: 'msg-u1',
        role: 'user',
        content: 'I have a question about my coverage.'
      };
      const assistantMsg: ChatMessage = {
        id: 'msg-a1',
        role: 'assistant',
        content: 'Your deductible is $1,500.'
      };

      const { container: userContainer } = render(<ChatMessageItem message={userMsg} onRerun={vi.fn()} />);
      const userToolbar = userContainer.querySelector('[data-testid="message-action-toolbar"]');
      expect(userToolbar).toBeInTheDocument();
      // Must NOT use legacy floating classes
      expect(userToolbar?.className).not.toContain('absolute');
      expect(userToolbar?.className).not.toContain('-top-');
      expect(userToolbar?.className).not.toContain('right-3');

      // The footer container row must have border-t
      const userFooter = userToolbar?.parentElement;
      expect(userFooter?.className).toContain('border-t');
      expect(userFooter?.className).toContain('justify-between');

      const { container: assistantContainer } = render(
        <ChatMessageItem message={assistantMsg} onRegenerate={vi.fn()} />
      );
      const assistantToolbar = assistantContainer.querySelector('[data-testid="message-action-toolbar"]');
      expect(assistantToolbar).toBeInTheDocument();
      expect(assistantToolbar?.className).not.toContain('absolute');
      expect(assistantToolbar?.className).not.toContain('-top-');

      const assistantFooter = assistantToolbar?.parentElement;
      expect(assistantFooter?.className).toContain('border-t');
      expect(assistantFooter?.className).toContain('justify-between');
    });

    it('remains fully visible inside an overflow-y-auto scroll container without negative margin clipping', () => {
      const longMessage: ChatMessage = {
        id: 'msg-scroll',
        role: 'assistant',
        content: 'Paragraph 1\n\nParagraph 2\n\nParagraph 3\n\nFinal instructions.'
      };

      // Wrap in simulated chat scroll container
      const { container } = render(
        <div data-testid="scroll-container" className="overflow-y-auto max-h-[300px] p-4">
          <ChatMessageItem message={longMessage} onRegenerate={vi.fn()} />
        </div>
      );

      const toolbar = container.querySelector('[data-testid="message-action-toolbar"]');
      expect(toolbar).toBeInTheDocument();

      // Ensure no parent or toolbar itself carries negative top margins that clip in scroll containers
      expect(toolbar?.className).not.toMatch(/-mt-\d+/);
      expect(toolbar?.className).not.toMatch(/-top-\d+/);
    });

    it('enforces card min-width so toolbar buttons never wrap or cause layout collapse on narrow 320px viewports', () => {
      const shortUserMsg: ChatMessage = {
        id: 'msg-short-u',
        role: 'user',
        content: 'Hi'
      };
      const shortAssistantMsg: ChatMessage = {
        id: 'msg-short-a',
        role: 'assistant',
        content: 'Ok'
      };

      const { container: uContainer } = render(<ChatMessageItem message={shortUserMsg} onRerun={vi.fn()} />);
      const userCard = uContainer.querySelector('[data-testid="chat-message-user"] > div');
      expect(userCard?.className).toContain('min-w-[200px]');

      const { container: aContainer } = render(
        <ChatMessageItem message={shortAssistantMsg} onRegenerate={vi.fn()} />
      );
      const assistantCard = aContainer.querySelector('[data-testid="chat-message-assistant"]');
      expect(assistantCard?.className).toContain('min-w-[240px]');
    });
  });

  // ===========================================================================
  // Dimension 2: Accessible Touch Targets & Touchscreen Usability
  // ===========================================================================
  describe('Dimension 2: Touch Targets & Touchscreen Ergonomics', () => {
    it('guarantees all toolbar action buttons meet accessible minimum size of >= 32px', () => {
      render(
        <MessageToolbar
          role="assistant"
          content="Test message"
          messageId="m1"
          onRegenerate={vi.fn()}
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');
      expect(copyBtn.className).toContain('min-w-[32px]');
      expect(copyBtn.className).toContain('min-h-[32px]');

      const regenBtn = screen.getByTestId('message-rerun-btn');
      expect(regenBtn.className).toContain('min-w-[32px]');
      expect(regenBtn.className).toContain('min-h-[32px]');
    });

    it('ensures user rerun button also meets >= 32px touch target', () => {
      render(
        <MessageToolbar
          role="user"
          content="User prompt"
          messageId="u1"
          onRerun={vi.fn()}
        />
      );

      const rerunBtn = screen.getByTestId('message-rerun-btn');
      expect(rerunBtn.className).toContain('min-w-[32px]');
      expect(rerunBtn.className).toContain('min-h-[32px]');
    });

    it('ensures toolbars are unconditionally visible (opacity-100) on touchscreens (< 640px) without hover', () => {
      // In touch environments there is no hover cursor. The class `opacity-100 sm:opacity-0 sm:group-hover:opacity-100`
      // guarantees that on viewports below `sm` (640px), the toolbar is always visible (opacity-100),
      // and only on desktop (sm:) hides until hover or focus.
      const { container: userContainer } = render(
        <MessageToolbar role="user" content="Hi" messageId="u1" onRerun={vi.fn()} />
      );
      const userToolbar = userContainer.querySelector('[data-testid="message-action-toolbar"]');
      expect(userToolbar?.className).toContain('opacity-100');
      expect(userToolbar?.className).toContain('sm:opacity-0');
      expect(userToolbar?.className).toContain('sm:group-hover:opacity-100');
      expect(userToolbar?.className).toContain('sm:group-focus-within:opacity-100');

      const { container: assistantContainer } = render(
        <MessageToolbar role="assistant" content="Hi" messageId="a1" onRegenerate={vi.fn()} />
      );
      const assistantToolbar = assistantContainer.querySelector('[data-testid="message-action-toolbar"]');
      expect(assistantToolbar?.className).toContain('opacity-100');
      expect(assistantToolbar?.className).toContain('sm:opacity-0');
      expect(assistantToolbar?.className).toContain('sm:group-hover:opacity-100');
      expect(assistantToolbar?.className).toContain('sm:group-focus-within:opacity-100');
    });

    it('renders role badges "You" and "Carefold Assistant" with high contrast and proper icons', () => {
      const userMsg: ChatMessage = { id: 'u1', role: 'user', content: 'What is covered?' };
      const assistantMsg: ChatMessage = { id: 'a1', role: 'assistant', content: 'Preventive care is covered.' };

      const { container: uContainer } = render(<ChatMessageItem message={userMsg} />);
      const userRole = uContainer.querySelector('[data-testid="message-role-user"]');
      expect(userRole).toBeInTheDocument();
      expect(userRole).toHaveTextContent('You');
      expect(userRole?.className).toContain('font-semibold');
      expect(userRole?.className).toContain('text-blue-50');

      const { container: aContainer } = render(<ChatMessageItem message={assistantMsg} />);
      const assistantRole = aContainer.querySelector('[data-testid="message-role-assistant"]');
      expect(assistantRole).toBeInTheDocument();
      expect(assistantRole).toHaveTextContent('Carefold Assistant');
      expect(assistantRole?.className).toContain('font-semibold');
      // Must include Bot icon next to Carefold Assistant
      const botIcon = assistantRole?.parentElement?.querySelector('svg');
      expect(botIcon).toBeInTheDocument();
    });

    it('supports custom agentTitle in role badge when provided', () => {
      const assistantMsg: ChatMessage = { id: 'a1', role: 'assistant', content: 'Ready.' };
      render(<ChatMessageItem message={assistantMsg} agentTitle="Visit Steward" />);

      const assistantRole = screen.getByTestId('message-role-assistant');
      expect(assistantRole).toHaveTextContent('Visit Steward');
    });
  });

  // ===========================================================================
  // Dimension 3: Tailwind Class Audit Oracle for ChatMessageItem & Components
  // ===========================================================================
  describe('Dimension 3: Tailwind CSS Class Validity Audit', () => {
    const invalidTailwindPatterns = [
      'shadow-xs',
      'shadow-2xs',
      'focus:outline-hidden',
      'backdrop-blur-xs'
    ];

    const m9ComponentFiles = [
      'apps/web/src/components/ChatMessageItem.tsx',
      'apps/web/src/components/chat/MessageToolbar.tsx',
      'apps/web/src/components/chat/CodeBlock.tsx'
    ];

    it('verifies ZERO invalid Tailwind CSS v3 classes exist in layout files', () => {
      const repoRoot = path.resolve(__dirname, '../../../../');
      const violations: Array<{ file: string; line: number; match: string }> = [];

      m9ComponentFiles.forEach((relPath) => {
        const fullPath = path.join(repoRoot, relPath);
        expect(fs.existsSync(fullPath), `File ${relPath} should exist`).toBe(true);

        const content = fs.readFileSync(fullPath, 'utf8');
        const lines = content.split('\n');

        lines.forEach((lineText, idx) => {
          invalidTailwindPatterns.forEach((pattern) => {
            if (lineText.includes(pattern)) {
              violations.push({
                file: relPath,
                line: idx + 1,
                match: pattern
              });
            }
          });
        });
      });

      expect(violations).toEqual([]);
    });

    it('verifies valid shadow-sm is used on message bubble surfaces', () => {
      const repoRoot = path.resolve(__dirname, '../../../../');
      const chatItemContent = fs.readFileSync(
        path.join(repoRoot, 'apps/web/src/components/ChatMessageItem.tsx'),
        'utf8'
      );
      expect(chatItemContent).toContain('shadow-sm');
      expect(chatItemContent).not.toContain('shadow-xs');
    });
  });

  // ===========================================================================
  // Dimension 4: Safe Refusal Guardrail & Collision Resistance
  // ===========================================================================
  describe('Dimension 4: Safe Refusal Guardrail & Header Collision Resistance', () => {
    it('isolates safe refusal badge at the top and action toolbar cleanly at the bottom without overlap', () => {
      const refusalMsg: ChatMessage = {
        id: 'msg-refusal-1',
        role: 'assistant',
        content: SAFE_REFUSAL_TEMPLATE,
        isRefusal: true,
        refusalReason: 'Clinical diagnosis requested'
      };

      const { container } = render(
        <ChatMessageItem message={refusalMsg} onRegenerate={vi.fn()} />
      );

      const card = container.querySelector('[data-testid="chat-message-refusal"]');
      expect(card).toBeInTheDocument();

      // Top elements
      const badge = screen.getByTestId('safe-refusal-badge');
      const callout = screen.getByTestId('refusal-reason-callout');
      expect(badge).toBeInTheDocument();
      expect(callout).toBeInTheDocument();

      // Bottom toolbar
      const toolbar = screen.getByTestId('message-action-toolbar');
      expect(toolbar).toBeInTheDocument();

      // Bottom footer has amber theme border
      const footer = toolbar.parentElement;
      expect(footer?.className).toContain('border-amber-200');

      // Toolbar is at the bottom of the card and NOT positioned top right colliding with the refusal badge
      expect(toolbar.className).not.toContain('-top-');
    });

    it('detects refusal correctly from SAFE_REFUSAL_SNIPPET even if isRefusal boolean is omitted', () => {
      const snippetMsg: ChatMessage = {
        id: 'msg-refusal-snippet',
        role: 'assistant',
        content: 'I am a wellness and care navigation assistant, not a licensed medical professional. Please seek urgent care.'
      };

      render(<ChatMessageItem message={snippetMsg} />);
      expect(screen.getByTestId('chat-message-refusal')).toBeInTheDocument();
      expect(screen.getByTestId('safe-refusal-badge')).toBeInTheDocument();
    });
  });

  // ===========================================================================
  // Dimension 5: CodeBlock Tokenizer, Streaming Fences & Edge Cases
  // ===========================================================================
  describe('Dimension 5: CodeBlock Tokenizer & Markdown Edge Cases', () => {
    it('normalizes esoteric and uppercase language tags gracefully', () => {
      expect(normalizeLanguage('PYTHON')).toBe('python');
      expect(normalizeLanguage('  JS  ')).toBe('javascript');
      expect(normalizeLanguage('CJS')).toBe('javascript');
      expect(normalizeLanguage('MJS')).toBe('javascript');
      expect(normalizeLanguage('ZSH')).toBe('bash');
      expect(normalizeLanguage('unknown_lang_xyz')).toBe('unknown_lang_xyz');
      expect(normalizeLanguage('')).toBe('text');
    });

    it('handles empty code block without throwing or crashing', () => {
      expect(() => render(<CodeBlock code="" language="python" />)).not.toThrow();
      expect(screen.getByTestId('code-block-language')).toHaveTextContent('python');
    });

    it('tokenizes SQL queries with keywords and comments', () => {
      const sqlCode = `-- Get user appointments\nSELECT id, date, doctor FROM appointments WHERE status = 'confirmed';`;
      const tokens = tokenizeCode(sqlCode, 'sql');

      expect(tokens.some((t) => t.type === 'comment')).toBe(true);
      expect(tokens.some((t) => t.type === 'keyword' && t.text === 'SELECT')).toBe(true);
      expect(tokens.some((t) => t.type === 'string' && t.text === "'confirmed'")).toBe(true);
    });

    it('tokenizes Bash script commands and options', () => {
      const bashCode = `# Deploy carefold\nexport PORT=3000\ncurl -s https://localhost:3000/api/health`;
      const tokens = tokenizeCode(bashCode, 'bash');

      expect(tokens.some((t) => t.type === 'comment')).toBe(true);
      expect(tokens.some((t) => t.type === 'keyword' && t.text === 'export')).toBe(true);
      expect(tokens.some((t) => t.type === 'keyword' && t.text === 'curl')).toBe(true);
    });

    it('safely handles malicious XSS / HTML tags inside code blocks without execution', () => {
      const xssCode = `const payload = "<script>alert('xss')</script><img src=x onerror=alert(1)>";`;
      render(<CodeBlock code={xssCode} language="typescript" />);

      expect(document.querySelector('script')).toBeNull();
      expect(document.querySelector('img')).toBeNull();
      expect(screen.getByTestId('code-block')).toHaveTextContent(/<script>alert/);
    });

    it('handles massive 500-line code snippet without tokenization recursion or timeout', () => {
      const lines = Array.from({ length: 500 }, (_, i) => `const step_${i} = ${i} * 2; // Step comment`);
      const massiveCode = lines.join('\n');

      const start = Date.now();
      const tokens = tokenizeCode(massiveCode, 'typescript');
      const duration = Date.now() - start;

      // Should tokenize in < 150ms
      expect(duration).toBeLessThan(150);
      expect(tokens.length).toBeGreaterThan(1000);

      expect(() => render(<CodeBlock code={massiveCode} language="typescript" />)).not.toThrow();
    });

    it('copies entire code content via copy button with checkmark confirmation', async () => {
      const writeTextSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
      const codeSnippet = 'export default function CareNav() { return <div>Carefold</div>; }';

      render(<CodeBlock code={codeSnippet} language="tsx" />);
      const copyBtn = screen.getByTestId('copy-code-btn');

      await act(async () => {
        fireEvent.click(copyBtn);
      });

      expect(writeTextSpy).toHaveBeenCalledWith(codeSnippet);
      expect(screen.getByTestId('copy-code-success')).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(2000);
      });

      expect(screen.queryByTestId('copy-code-success')).not.toBeInTheDocument();
    });
  });

  // ===========================================================================
  // Dimension 6: Timestamp Robustness & Graceful Degradation
  // ===========================================================================
  describe('Dimension 6: Timestamp Formatting & Edge Case Handling', () => {
    it('formats ISO 8601 timestamps safely', () => {
      const formatted = formatMessageTimestamp('2026-09-30T15:45:00.000Z');
      expect(formatted).not.toBeNull();
      expect(formatted).toMatch(/\d{1,2}:\d{2}/);
    });

    it('gracefully returns null for undefined, null, or garbage timestamps', () => {
      expect(formatMessageTimestamp(undefined)).toBeNull();
      expect(formatMessageTimestamp('')).toBeNull();
      expect(formatMessageTimestamp('not-a-timestamp')).toBeNull();
      expect(formatMessageTimestamp('NaN')).toBeNull();
    });

    it('renders time element with datetime attribute when timestamp is valid', () => {
      const msg: ChatMessage = {
        id: 'msg-time-valid',
        role: 'user',
        content: 'Check timestamp',
        timestamp: '2026-09-30T10:00:00Z'
      };

      render(<ChatMessageItem message={msg} />);
      const timeEl = screen.getByTestId('message-timestamp');
      expect(timeEl).toBeInTheDocument();
      expect(timeEl).toHaveAttribute('dateTime', '2026-09-30T10:00:00Z');
    });
  });

  // ===========================================================================
  // Dimension 7: Interaction State Management (Disabled, Streaming)
  // ===========================================================================
  describe('Dimension 7: Disabled and Streaming States', () => {
    it('disables rerun button when disabled=true on user message', () => {
      const onRerun = vi.fn();
      render(
        <MessageToolbar
          role="user"
          content="Test"
          messageId="u1"
          onRerun={onRerun}
          disabled={true}
        />
      );

      const rerunBtn = screen.getByTestId('message-rerun-btn');
      expect(rerunBtn).toBeDisabled();
      fireEvent.click(rerunBtn);
      expect(onRerun).not.toHaveBeenCalled();
    });

    it('disables regenerate button when disabled=true or isStreaming=true on assistant message', () => {
      const onRegenerate = vi.fn();
      const { rerender } = render(
        <MessageToolbar
          role="assistant"
          content="Test"
          messageId="a1"
          onRegenerate={onRegenerate}
          disabled={true}
        />
      );

      const regenBtn = screen.getByTestId('message-rerun-btn');
      expect(regenBtn).toBeDisabled();
      fireEvent.click(regenBtn);
      expect(onRegenerate).not.toHaveBeenCalled();

      // Test isStreaming=true
      rerender(
        <MessageToolbar
          role="assistant"
          content="Test"
          messageId="a1"
          onRegenerate={onRegenerate}
          disabled={false}
          isStreaming={true}
        />
      );
      expect(regenBtn).toBeDisabled();
    });

    it('hides assistant action toolbar completely during active streaming in ChatMessageItem', () => {
      const streamingMsg: ChatMessage = {
        id: 'msg-streaming',
        role: 'assistant',
        content: 'Currently generating words...',
        isStreaming: true
      };

      render(<ChatMessageItem message={streamingMsg} onRegenerate={vi.fn()} />);

      // Assistant toolbar should NOT be rendered while streaming
      expect(screen.queryByTestId('message-action-toolbar')).not.toBeInTheDocument();
      // Streaming pulse indicator should be rendered
      expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
    });
  });
});
