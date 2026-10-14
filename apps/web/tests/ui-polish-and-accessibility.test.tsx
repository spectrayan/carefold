/*
 * Carefold — Healthcare AI Agent Marketplace & Runtime
 * Copyright 2026 Spectrayan (https://spectrayan.com)
 *
 * Licensed under the PolyForm Noncommercial License 1.0.0 and the
 * Carefold Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
 * Personal and household local use only. Commercial use, hosted service
 * offering, rebranding, white-labeling, and redistribution of modified
 * forks are prohibited without a written commercial license from Spectrayan.
 *
 * Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import fs from 'node:fs';
import path from 'node:path';

import { StartersChips } from '@/components/StartersChips';
import { SuggestedQuestionsChips } from '@/components/SuggestedQuestionsChips';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';
import { SafetyDisclaimerBanner } from '@/components/SafetyDisclaimerBanner';
import { FirstRunSetupCard } from '@/components/setup/FirstRunSetupCard';
import { AgentDetailClient } from '@/app/agents/[id]/AgentDetailClient';
import { ChatClient } from '@/app/chat/ChatClient';
import { formatFriendlyChatError } from '@/lib/chatErrors';
import { RISK_CLASS_OPTIONS, type AgentSummary } from '@/lib/types';
import { calculateContrastRatio } from './contrast.test';

vi.mock('@/components/ThemeScript', () => ({
  ThemeScript: () => null,
}));

const repoRoot = path.resolve(__dirname, '../../../');

const sampleAgentSummary: AgentSummary = {
  id: 'visit-steward',
  title: 'Visit Steward',
  version: '0.4.0',
  risk_class: 'wellness',
  skills: ['visit-prep'],
  effectiveTools: ['attach-read', 'workspace-note'],
  starters: ['Help me prepare a prioritized list of questions for my annual physical next week.'],
  description: 'Organizes questions and checklists for upcoming clinic visits.',
};

describe('Web UI Polish, Accessibility & Plain-Language Verification (#171–#183)', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  // ---------------------------------------------------------------------------
  // #171 — Chat Viewport & Mobile Overflow
  // ---------------------------------------------------------------------------
  describe('Chat Viewport & Multi-Line Prompt Wrapping (#171)', () => {
    it('wraps multi-line prompts in StartersChips and SuggestedQuestionsChips without horizontal overflow', () => {
      const longPrompt =
        'Help me organize a comprehensive 30-day symptom and medication log for my upcoming specialist appointment';

      render(
        <div>
          <StartersChips starters={[longPrompt]} onSelectStarter={vi.fn()} />
          <SuggestedQuestionsChips suggestions={[longPrompt]} onSelectSuggestion={vi.fn()} />
        </div>
      );

      const starterChip = screen.getByTestId('starter-chip');
      expect(starterChip.className).toContain('whitespace-normal');
      expect(starterChip.className).toContain('break-words');
      expect(starterChip.className).toContain('text-left');

      const suggestionChip = screen.getByTestId('suggested-question-chip');
      expect(suggestionChip.className).toContain('whitespace-normal');
      expect(suggestionChip.className).toContain('break-words');
      expect(suggestionChip.className).toContain('text-left');
    });

    it('uses clean flex container sizing on ChatClient root without brittle calc(100dvh-120px) height math', () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
      );

      const { container } = render(<ChatClient initialAgents={[sampleAgentSummary]} />);
      const chatRoot = container.querySelector('[data-chat-page="true"]');
      expect(chatRoot).not.toBeNull();
      expect(chatRoot?.className).toContain('h-full');
      expect(chatRoot?.className).toContain('flex-1');
      expect(chatRoot?.className).toContain('min-h-0');
      expect(chatRoot?.className).toContain('flex');
      expect(chatRoot?.className).toContain('flex-col');
      expect(chatRoot?.className).not.toContain('calc(100dvh-120px)');
    });
  });

  // ---------------------------------------------------------------------------
  // #172 — WCAG AA Primary Buttons & Green Text
  // ---------------------------------------------------------------------------
  describe('WCAG AA Primary Button & Green Text Contrast (#172)', () => {
    it('verifies emerald-700 (#047857) with white (#ffffff) meets >= 4.5:1 WCAG AA contrast', () => {
      const contrastRatio = calculateContrastRatio('#047857', '#ffffff');
      expect(contrastRatio).toBeGreaterThanOrEqual(4.5);
    });
  });

  // ---------------------------------------------------------------------------
  // #173 — Unified Keyboard :focus-visible Ring
  // ---------------------------------------------------------------------------
  describe('Global Keyboard :focus-visible Ring (#173)', () => {
    it('defines a unified global :focus-visible outline rule in globals.css', () => {
      const globalsCssPath = path.join(repoRoot, 'apps/web/src/app/globals.css');
      const css = fs.readFileSync(globalsCssPath, 'utf8');

      expect(css).toContain('a:focus-visible');
      expect(css).toContain('button:focus-visible');
      expect(css).toContain('input:focus-visible');
      expect(css).toContain('select:focus-visible');
      expect(css).toContain('textarea:focus-visible');
      expect(css).toContain('summary:focus-visible');
      expect(css).toContain('[role="button"]:focus-visible');
      expect(css).toContain('outline: 2px solid var(--cf-accent, #047857)');
      expect(css).toContain('outline-offset: 2px');
    });
  });

  // ---------------------------------------------------------------------------
  // #175 — Plain-Language Starter Prompts & Developer Disclosure
  // ---------------------------------------------------------------------------
  describe('Plain-Language Starter Prompts & Developer Disclosure (#175)', () => {
    it('verifies all bundled agents/*/starters.json files contain zero developer attachments/ file paths', () => {
      const agentsDir = path.join(repoRoot, 'agents');
      const entries = fs.readdirSync(agentsDir, { withFileTypes: true });

      let checkedCount = 0;
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const startersPath = path.join(agentsDir, entry.name, 'starters.json');
        if (fs.existsSync(startersPath)) {
          checkedCount++;
          const raw = fs.readFileSync(startersPath, 'utf8');
          expect(raw, `${entry.name}/starters.json should not contain attachments/ paths`).not.toContain(
            'attachments/'
          );
        }
      }
      expect(checkedCount).toBeGreaterThan(15);
    });

    it('renders collapsible <details data-testid="agent-developer-details"> with <summary>For developers</summary>', () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(new Response(JSON.stringify({ docs: [] }), { status: 200 }))
      );

      render(
        <AgentDetailClient
          agent={{
            id: 'visit-steward',
            title: 'Visit Steward',
            version: '0.4.0',
            risk_class: 'wellness',
            model: 'llama3.2',
            skills: [],
            effectiveTools: ['attach-read', 'workspace-note'],
            forbidden: ['Diagnosing medical conditions'],
            persona: 'Assist patients with organizing questions for their visit.',
            starters: ['Help me prepare a prioritized list of questions for my annual physical next week.'],
            description: 'Organizes questions and checklists for upcoming clinic visits.',
          }}
        />
      );

      const devDetails = screen.getByTestId('agent-developer-details');
      expect(devDetails.tagName.toLowerCase()).toBe('details');

      const summary = devDetails.querySelector('summary');
      expect(summary).not.toBeNull();
      expect(summary?.textContent).toContain('For developers');
    });
  });

  // ---------------------------------------------------------------------------
  // #176 — Friendly Inline Chat Error Notice
  // ---------------------------------------------------------------------------
  describe('Friendly Inline Chat Error Notice (#176)', () => {
    it('maps missing API key, Ollama connection refused, rate limit, and timeout errors to friendly summaries with technicalDetails', () => {
      const apiKeyErr = formatFriendlyChatError('HTTP 401: Unauthorized missing_api_key');
      expect(apiKeyErr.summary).toContain('API key');
      expect(apiKeyErr.actionHint).toContain('Settings');
      expect(apiKeyErr.technicalDetails).toContain('missing_api_key');

      const ollamaErr = formatFriendlyChatError('connect ECONNREFUSED 127.0.0.1:11434');
      expect(ollamaErr.summary).toContain('Cannot connect to the model service');
      expect(ollamaErr.actionHint).toContain('Ollama');
      expect(ollamaErr.technicalDetails).toContain('11434');

      const rateLimitErr = formatFriendlyChatError('HTTP 429: Rate limit exceeded for model');
      expect(rateLimitErr.summary.toLowerCase()).toContain('busy');
      expect(rateLimitErr.actionHint).toContain('Try again');
      expect(rateLimitErr.technicalDetails).toContain('429');

      const timeoutErr = formatFriendlyChatError('Gateway Timeout 504: request timed out');
      expect(timeoutErr.summary).toContain('took too long');
      expect(timeoutErr.actionHint).toContain('Try again');
      expect(timeoutErr.technicalDetails).toContain('504');
    });

    it('renders data-testid="chat-error-notice", "chat-error-retry", and "chat-error-details" on ChatMessageItem when message.error is set', () => {
      const onRetry = vi.fn();
      const failedMessage: ChatMessage = {
        id: 'assistant-err-1',
        role: 'assistant',
        content: '',
        error: 'connect ECONNREFUSED 127.0.0.1:11434',
      };

      render(
        <ChatMessageItem
          message={failedMessage}
          onRetry={onRetry}
          agentTitle="Visit Steward"
        />
      );

      const errorNotice = screen.getByTestId('chat-error-notice');
      expect(errorNotice).toBeInTheDocument();
      expect(errorNotice).toHaveTextContent(/Cannot connect to the model service/i);

      const retryBtn = screen.getByTestId('chat-error-retry');
      expect(retryBtn).toBeInTheDocument();
      expect(retryBtn).toHaveTextContent('Try again');
      fireEvent.click(retryBtn);
      expect(onRetry).toHaveBeenCalledWith('assistant-err-1');

      const errorDetails = screen.getByTestId('chat-error-details');
      expect(errorDetails).toBeInTheDocument();
      expect(errorDetails).toHaveTextContent('Technical details');
      expect(errorDetails).toHaveTextContent('ECONNREFUSED');
    });
  });

  // ---------------------------------------------------------------------------
  // #177 — Retire Off-Brand Blue & Purple Accents
  // ---------------------------------------------------------------------------
  describe('Warm Stone & Emerald Token Palette (#177)', () => {
    it('renders ChatMessageItem user bubble without off-brand bg-blue-600', () => {
      const userMessage: ChatMessage = {
        id: 'user-msg-1',
        role: 'user',
        content: 'What questions should I ask my cardiologist?',
      };

      render(<ChatMessageItem message={userMessage} />);

      const userBubbleWrapper = screen.getByTestId('chat-message-user');
      expect(userBubbleWrapper.innerHTML).not.toContain('bg-blue-600');
    });
  });

  // ---------------------------------------------------------------------------
  // #178 — Quiet Persistent One-Line Safety Notice
  // ---------------------------------------------------------------------------
  describe('Quiet Persistent Safety Notice (#178)', () => {
    it('renders SafetyDisclaimerBanner with data-testid="safety-disclaimer-banner" and "safety-disclaimer-learn-more"', () => {
      render(<SafetyDisclaimerBanner />);

      const banner = screen.getByTestId('safety-disclaimer-banner');
      expect(banner).toBeInTheDocument();

      const learnMore = screen.getByTestId('safety-disclaimer-learn-more');
      expect(learnMore).toBeInTheDocument();
      expect(learnMore).toHaveTextContent('Learn more');
    });
  });

  // ---------------------------------------------------------------------------
  // #179 — Compact Readiness Row When Setup Passes
  // ---------------------------------------------------------------------------
  describe('Compact Readiness Row (#179)', () => {
    it('renders compact readiness row (data-testid="first-run-ready-compact") when READY and full checklist when ACTION_REQUIRED', () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({
              status: 'ok',
              backendReachable: true,
              workspace: { root: '/workspace', agentsCount: 22, skillsCount: 24 },
              ollama: { status: 'connected', endpoint: 'http://127.0.0.1:11434', reachable: true },
              models: [{ id: 'llama3.2', name: 'Llama 3.2' }],
            }),
            { status: 200 }
          )
        )
      );

      const { unmount } = render(<FirstRunSetupCard status="READY" />);
      const compactRow = screen.getByTestId('first-run-ready-compact');
      expect(compactRow).toBeInTheDocument();
      expect(compactRow).toHaveTextContent(/All set/i);

      unmount();

      render(<FirstRunSetupCard status="ACTION_REQUIRED" />);
      expect(screen.queryByTestId('first-run-ready-compact')).not.toBeInTheDocument();
      expect(screen.getByTestId('setup-checklist')).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // #180 — Simplify Marketplace Cards & Remove Unused education Filter
  // ---------------------------------------------------------------------------
  describe('Marketplace Filter Simplification (#180)', () => {
    it('verifies RISK_CLASS_OPTIONS does not include unused "education" filter', () => {
      expect(RISK_CLASS_OPTIONS).toEqual(['wellness', 'admin', 'clinical_assist']);
      expect(RISK_CLASS_OPTIONS).not.toContain('education');
    });
  });

  // ---------------------------------------------------------------------------
  // #181, #182, #183 — Typography Floor, Touch Targets & No-Op Animations
  // ---------------------------------------------------------------------------
  describe('Typography Floor (>= 12px) & No-Op Animation Removal (#181, #182, #183)', () => {
    it('verifies key components contain zero text-[9px], text-[10px], text-[11px], or animate-in classes', () => {
      const targetFiles = [
        'apps/web/src/components/ChatMessageItem.tsx',
        'apps/web/src/components/Navbar.tsx',
        'apps/web/src/app/MarketplaceClient.tsx',
        'apps/web/src/app/skills/SkillsClient.tsx',
        'apps/web/src/app/chat/ChatClient.tsx',
      ];

      for (const relPath of targetFiles) {
        const content = fs.readFileSync(path.join(repoRoot, relPath), 'utf8');
        expect(content, `${relPath} must not use micro-text < 12px`).not.toMatch(
          /\btext-\[(?:9|10|11)px\]/
        );
        expect(content, `${relPath} must not use no-op animate-in utility`).not.toMatch(
          /\banimate-in\b/
        );
      }
    });
  });
});
