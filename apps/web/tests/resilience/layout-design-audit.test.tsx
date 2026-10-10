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
import { render, screen } from '@testing-library/react';
import React from 'react';
import fs from 'fs';
import path from 'path';
import { StartersChips } from '@/components/StartersChips';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { MessageToolbar } from '@/components/chat/MessageToolbar';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import { Navbar } from '@/components/Navbar';
import { ChatClient } from '@/app/chat/ChatClient';
import type { AgentSummary } from '@/lib/types';

// Mock agents for testing
const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.1.0',
    risk_class: 'wellness',
    skills: ['visit-prep'],
    effectiveTools: ['skill-docs'],
    starters: ['What questions should I ask my doctor about my symptoms?']
  }
];

describe('Layout & Dead-Code Verification Suite', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  // =========================================================================
  // Challenge #171: 100dvh Layout & Zero Outer Page Scrollbars on /chat
  // =========================================================================
  describe('Challenge #171: 100dvh Layout & Zero Outer Page Scrollbars', () => {
    const globalsCssPath = path.resolve(__dirname, '../../src/app/globals.css');

    it('asserts globals.css defines 100dvh bounds and overflow:hidden on body:has([data-chat-page])', () => {
      expect(fs.existsSync(globalsCssPath)).toBe(true);
      const css = fs.readFileSync(globalsCssPath, 'utf8');

      // Rule block must target body:has([data-chat-page])
      expect(css).toContain('body:has([data-chat-page])');

      // Must set overflow: hidden and 100dvh
      const bodyChatBlockMatch = css.match(/body:has\(\[data-chat-page\]\)\s*\{([^}]+)\}/);
      expect(bodyChatBlockMatch).not.toBeNull();
      const bodyChatProps = bodyChatBlockMatch![1];
      expect(bodyChatProps).toContain('overflow: hidden');
      expect(bodyChatProps).toContain('height: 100dvh');
      expect(bodyChatProps).toContain('max-height: 100dvh');
    });

    it('asserts globals.css isolates main element with flex:1, min-height:0, and overflow:hidden', () => {
      const css = fs.readFileSync(globalsCssPath, 'utf8');
      const mainChatBlockMatch = css.match(/body:has\(\[data-chat-page\]\)\s+main\s*\{([^}]+)\}/);
      expect(mainChatBlockMatch).not.toBeNull();
      const mainChatProps = mainChatBlockMatch![1];
      expect(mainChatProps).toContain('overflow: hidden !important');
      expect(mainChatProps).toContain('flex: 1 1 0% !important');
      expect(mainChatProps).toContain('min-height: 0 !important');
      expect(mainChatProps).toContain('padding: 0 !important');
    });

    it('asserts globals.css suppresses outer footer on /chat to avoid page-level scrollbars', () => {
      const css = fs.readFileSync(globalsCssPath, 'utf8');
      const footerChatBlockMatch = css.match(/body:has\(\[data-chat-page\]\)\s+footer\s*\{([^}]+)\}/);
      expect(footerChatBlockMatch).not.toBeNull();
      const footerChatProps = footerChatBlockMatch![1];
      expect(footerChatProps).toContain('display: none !important');
    });

    it('renders ChatClient and verifies root container carries data-chat-page and inner scroll container isolation', () => {
      const { container } = render(<ChatClient initialAgents={mockAgents} />);

      const chatRoot = container.querySelector('[data-chat-page="true"]');
      expect(chatRoot).toBeInTheDocument();
      expect(chatRoot?.className).toContain('overflow-hidden');
      expect(chatRoot?.className).toContain('flex-1');
      expect(chatRoot?.className).toContain('min-h-0');

      // The internal message log must isolate scroll to overflow-y-auto and suppress horizontal scroll
      const messageLog = container.querySelector('[role="log"]');
      expect(messageLog).toBeInTheDocument();
      expect(messageLog?.className).toContain('overflow-y-auto');
      expect(messageLog?.className).toContain('overflow-x-hidden');
    });
  });

  // =========================================================================
  // Challenge #172: Mobile 390px/320px Zero Horizontal Overflow
  // =========================================================================
  describe('Challenge #172: Mobile 390px/320px Zero Horizontal Overflow', () => {
    it('verifies StartersChips wrap and break long/unbroken strings without overflow', () => {
      const adversarialStarters = [
        'Short prompt',
        'A moderately long question about prescription benefits and prior authorization requirements',
        'https://health.example.com/very/long/unbroken/path/that/could/overflow/mobile/viewport/if/not/broken',
        'Pneumonoultramicroscopicsilicovolcanoconiosis-diagnostic-evaluation-protocol'
      ];

      const { container } = render(
        <div style={{ width: 320 }} data-testid="viewport-320">
          <StartersChips starters={adversarialStarters} onSelectStarter={vi.fn()} />
        </div>
      );

      const startersContainer = container.querySelector('[data-testid="starters-container"]');
      expect(startersContainer).toBeInTheDocument();
      expect(startersContainer?.className).toContain('flex-wrap');

      const chips = container.querySelectorAll('[data-testid="starter-chip"]');
      expect(chips.length).toBe(4);

      chips.forEach((chip) => {
        expect(chip.className).toContain('max-w-full');
        const span = chip.querySelector('span');
        expect(span?.className).toContain('break-words');
        expect(span?.className).toContain('whitespace-normal');
        expect(span?.className).toContain('max-w-full');
      });
    });

    it('verifies SuggestedQuestionsChips wrap and break without overflow', () => {
      const adversarialSuggestions = [
        'How do I request an appeal for a denied cardiology referral?',
        'https://verylongunbrokensuggestionstringwithoutanyspaceswhatsoever1234567890.example.com'
      ];

      const { container } = render(
        <div style={{ width: 320 }} data-testid="viewport-320">
          <SuggestedQuestionsChips suggestions={adversarialSuggestions} onSelectSuggestion={vi.fn()} />
        </div>
      );

      const chips = container.querySelectorAll('[data-testid="suggested-question-chip"]');
      expect(chips.length).toBe(2);

      chips.forEach((chip) => {
        expect(chip.className).toContain('max-w-full');
        const span = chip.querySelector('span');
        expect(span?.className).toContain('break-words');
        expect(span?.className).toContain('whitespace-normal');
        expect(span?.className).toContain('max-w-full');
      });
    });

    it('verifies ChatMessageItem min-width boundaries prevent layout blowout while fitting in 320px', () => {
      const shortUser: ChatMessage = { id: 'u1', role: 'user', content: 'Hi' };
      const shortAssistant: ChatMessage = { id: 'a1', role: 'assistant', content: 'Hello' };

      const { container: uContainer } = render(
        <div style={{ width: 320 }}>
          <ChatMessageItem message={shortUser} />
        </div>
      );
      const userCard = uContainer.querySelector('[data-testid="chat-message-user"] > div');
      // min-w-[200px] ensures action toolbar fits without wrapping, and 200px < 320px mobile viewport
      expect(userCard?.className).toContain('min-w-[200px]');

      const { container: aContainer } = render(
        <div style={{ width: 320 }}>
          <ChatMessageItem message={shortAssistant} />
        </div>
      );
      const assistantCard = aContainer.querySelector('[data-testid="chat-message-assistant"]');
      // min-w-[240px] ensures assistant toolbar fits, and 240px < (320px - 32px padding) = 288px
      expect(assistantCard?.className).toContain('min-w-[240px]');
    });
  });

  // =========================================================================
  // Challenge #182: 44x44px Touch Targets Across Interactive Controls
  // =========================================================================
  describe('Challenge #182: 44x44px Touch Targets Verification', () => {
    it('verifies StartersChips satisfy 44px min-height hitbox requirement', () => {
      render(<StartersChips starters={['Test prompt']} onSelectStarter={vi.fn()} />);
      const chip = screen.getByTestId('starter-chip');
      expect(chip.className).toContain('min-h-[44px]');
      expect(chip.className).toContain('px-3.5');
    });

    it('verifies SuggestedQuestionsChips satisfy 44px min-height hitbox requirement', () => {
      render(<SuggestedQuestionsChips suggestions={['Test question']} onSelectSuggestion={vi.fn()} />);
      const chip = screen.getByTestId('suggested-question-chip');
      expect(chip.className).toContain('min-h-[44px]');
      expect(chip.className).toContain('px-3.5');
    });

    it('verifies MessageToolbar buttons satisfy 44x44px hitbox requirement', () => {
      render(
        <MessageToolbar
          role="assistant"
          content="Copyable text"
          messageId="m1"
          onRegenerate={vi.fn()}
        />
      );

      const copyBtn = screen.getByTestId('message-copy-btn');
      expect(copyBtn.className).toContain('min-w-[44px]');
      expect(copyBtn.className).toContain('min-h-[44px]');

      const regenBtn = screen.getByTestId('message-rerun-btn');
      expect(regenBtn.className).toContain('min-w-[44px]');
      expect(regenBtn.className).toContain('min-h-[44px]');
    });

    it('verifies Navbar theme toggle and mobile menu toggle satisfy 44x44px hitbox requirement', () => {
      render(<Navbar />);

      const themeToggle = screen.getByTestId('theme-toggle-btn');
      expect(themeToggle.className).toContain('min-w-[44px]');
      expect(themeToggle.className).toContain('min-h-[44px]');

      const mobileToggle = screen.getByTestId('mobile-menu-toggle');
      expect(mobileToggle.className).toContain('min-w-[44px]');
      expect(mobileToggle.className).toContain('min-h-[44px]');
    });

    it('verifies ChatComposer textarea and submit/stop buttons satisfy 44px touch targets', () => {
      const { container } = render(<ChatClient initialAgents={mockAgents} />);

      const textarea = container.querySelector('textarea');
      expect(textarea).toBeInTheDocument();
      expect(textarea?.className).toContain('min-h-[44px]');

      const submitBtn = screen.getByTestId('chat-submit-btn');
      expect(submitBtn.className).toContain('min-w-[44px]');
      expect(submitBtn.className).toContain('min-h-[44px]');
    });
  });

  // =========================================================================
  // Challenge #184: Dead Components Purged & Zero Broken Imports
  // =========================================================================
  describe('Challenge #184: Dead Component Purge & Zero Broken Imports', () => {
    const webSrcDir = path.resolve(__dirname, '../../src');
    const componentsDir = path.resolve(webSrcDir, 'components');

    const purgedLegacyFiles = [
      'ThinkingIndicator.tsx',
      'CodeBlock.tsx',
      'ScrollToBottomButton.tsx',
      'DisclaimerHeader.tsx'
    ];

    it('asserts the 4 purged components do NOT exist in apps/web/src/components/', () => {
      purgedLegacyFiles.forEach((file) => {
        const filePath = path.join(componentsDir, file);
        expect(fs.existsSync(filePath), `Legacy file ${file} must NOT exist`).toBe(false);
      });
    });

    it('asserts active canonical components exist in apps/web/src/components/chat/', () => {
      const activeChatDir = path.join(componentsDir, 'chat');
      expect(fs.existsSync(path.join(activeChatDir, 'ThinkingIndicator.tsx'))).toBe(true);
      expect(fs.existsSync(path.join(activeChatDir, 'CodeBlock.tsx'))).toBe(true);
      expect(fs.existsSync(path.join(activeChatDir, 'ScrollToBottomButton.tsx'))).toBe(true);
    });

    it('verifies ZERO broken imports across all src and test files for purged paths', () => {
      const webDir = path.resolve(__dirname, '../..');
      const allFiles: string[] = [];

      function walkSync(dir: string) {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const entry of entries) {
          const full = path.join(dir, entry.name);
          if (entry.isDirectory()) {
            if (entry.name !== 'node_modules' && entry.name !== '.next') {
              walkSync(full);
            }
          } else if (entry.isFile() && (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx'))) {
            allFiles.push(full);
          }
        }
      }

      walkSync(path.join(webDir, 'src'));
      walkSync(path.join(webDir, 'tests'));

      const danglingImportPatterns = [
        /@\/components\/ThinkingIndicator['"]/,
        /@\/components\/CodeBlock['"]/,
        /@\/components\/ScrollToBottomButton['"]/
      ];

      const brokenMatches: Array<{ file: string; line: number; text: string }> = [];

      allFiles.forEach((file) => {
        const content = fs.readFileSync(file, 'utf8');
        const lines = content.split('\n');
        lines.forEach((lineText, idx) => {
          danglingImportPatterns.forEach((pat) => {
            if (pat.test(lineText)) {
              brokenMatches.push({ file: path.relative(webDir, file), line: idx + 1, text: lineText });
            }
          });
        });
      });

      expect(brokenMatches).toEqual([]);
    });
  });
});
