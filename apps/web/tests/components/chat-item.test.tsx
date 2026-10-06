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

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ChatMessageItem, stripReferencePreamble, type ChatMessage } from '@/components/ChatMessageItem';
import { SAFE_REFUSAL_TEMPLATE } from '@/types/api';

describe('ChatMessageItem Component', () => {
  // Existing baseline tests
  it('renders user message bubble in right-aligned container', () => {
    const message: ChatMessage = {
      id: 'm-1',
      role: 'user',
      content: 'What questions should I ask my doctor?'
    };

    render(<ChatMessageItem message={message} />);
    expect(screen.getByTestId('chat-message-user')).toHaveTextContent('What questions should I ask my doctor?');
  });

  it('renders streaming indicator cursor when isStreaming is true', () => {
    const message: ChatMessage = {
      id: 'm-2',
      role: 'assistant',
      content: 'Generating your preparation list...',
      isStreaming: true
    };

    render(<ChatMessageItem message={message} />);
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
  });

  it('embeds ToolTraceCard when assistant message includes toolTraces', () => {
    const message: ChatMessage = {
      id: 'm-3',
      role: 'assistant',
      content: 'I loaded your visit guide.',
      toolTraces: [
        {
          id: 't-1',
          tool: 'skill-docs',
          status: 'completed',
          input: { skill_id: 'visit-prep', doc: 'checklist.md' },
          duration_ms: 15
        }
      ]
    };

    render(<ChatMessageItem message={message} />);
    expect(screen.getByTestId('embedded-tool-traces')).toBeInTheDocument();
    expect(screen.getByText('skill-docs')).toBeInTheDocument();
  });

  it('renders Safe Refusal badge, amber border, and template cleanly when refused', () => {
    const message: ChatMessage = {
      id: 'm-4',
      role: 'assistant',
      content: SAFE_REFUSAL_TEMPLATE,
      isRefusal: true,
      refusalReason: 'Prohibited clinical diagnosis request'
    };

    render(<ChatMessageItem message={message} />);

    const container = screen.getByTestId('chat-message-refusal');
    expect(container).toBeInTheDocument();
    expect(container.className).toContain('border-amber-500');

    expect(screen.getByTestId('safe-refusal-badge')).toHaveTextContent('Safety Refusal Gate: Protected Clinical Boundary');
    expect(screen.getByTestId('refusal-reason-callout')).toHaveTextContent('Prohibited clinical diagnosis request');
    expect(container).toHaveTextContent(SAFE_REFUSAL_TEMPLATE);
  });

  it('renders assistant message with clinical boundary disclaimer when boundaryWarning is true', () => {
    const message: ChatMessage = {
      id: 'm-tier2',
      role: 'assistant',
      content: 'Here are details on hypertension and questions you can ask your doctor.',
      boundaryWarning: true,
      boundaryReason: 'forbidden_intent:diagnose'
    };

    render(<ChatMessageItem message={message} />);

    // Should NOT be replaced with refusal gate box
    expect(screen.getByTestId('chat-message-assistant')).toBeInTheDocument();
    expect(screen.queryByTestId('chat-message-refusal')).not.toBeInTheDocument();
    expect(screen.queryByTestId('safe-refusal-badge')).not.toBeInTheDocument();

    // Content is preserved
    expect(screen.getByText(/Here are details on hypertension/)).toBeInTheDocument();

    // Clinical boundary notice disclaimer card is rendered
    const disclaimer = screen.getByTestId('clinical-boundary-disclaimer');
    expect(disclaimer).toBeInTheDocument();
    expect(disclaimer).toHaveTextContent('Clinical Boundary Notice');
    expect(disclaimer).toHaveTextContent('diagnose');
    expect(disclaimer).toHaveTextContent('Carefold provides educational context and visit preparation checklists');
  });

  // -------------------------------------------------------------------------
  // M9 Enhancements: Role Badges
  // -------------------------------------------------------------------------
  it('renders subtle "You" role badge on user message', () => {
    const message: ChatMessage = {
      id: 'm-u-role',
      role: 'user',
      content: 'Hello, need help.'
    };

    render(<ChatMessageItem message={message} />);
    const roleBadge = screen.getByTestId('message-role-user');
    expect(roleBadge).toBeInTheDocument();
    expect(roleBadge).toHaveTextContent('You');
  });

  it('renders subtle "Carefold Assistant" role badge with Bot icon on assistant message', () => {
    const message: ChatMessage = {
      id: 'm-a-role',
      role: 'assistant',
      content: 'I can assist you with your health benefits.'
    };

    render(<ChatMessageItem message={message} />);
    const roleBadge = screen.getByTestId('message-role-assistant');
    expect(roleBadge).toBeInTheDocument();
    expect(roleBadge).toHaveTextContent('Carefold Assistant');
  });

  // -------------------------------------------------------------------------
  // M9 Enhancements: Theme-Aware Timestamps
  // -------------------------------------------------------------------------
  it('renders formatted timestamp with theme-aware text-blue-100 on user message', () => {
    const message: ChatMessage = {
      id: 'm-u-time',
      role: 'user',
      content: 'Timestamped user message',
      timestamp: '2026-09-30T14:30:00Z'
    };

    render(<ChatMessageItem message={message} />);
    const timestampEl = screen.getByTestId('message-timestamp');
    expect(timestampEl).toBeInTheDocument();
    expect(timestampEl.className).toContain('text-blue-100');
  });

  it('renders formatted timestamp with theme-aware slate/zinc classes on assistant message', () => {
    const message: ChatMessage = {
      id: 'm-a-time',
      role: 'assistant',
      content: 'Timestamped assistant message',
      timestamp: '2026-09-30T14:30:00Z'
    };

    render(<ChatMessageItem message={message} />);
    const timestampEl = screen.getByTestId('message-timestamp');
    expect(timestampEl).toBeInTheDocument();
    expect(timestampEl.className).toContain('text-slate-500');
    expect(timestampEl.className).toContain('dark:text-zinc-400');
  });

  it('omits timestamp element when message.timestamp is missing or undefined', () => {
    const message: ChatMessage = {
      id: 'm-no-time',
      role: 'assistant',
      content: 'Message without timestamp'
    };

    render(<ChatMessageItem message={message} />);
    expect(screen.queryByTestId('message-timestamp')).not.toBeInTheDocument();
  });

  it('handles invalid timestamp strings gracefully without throwing errors', () => {
    const message: ChatMessage = {
      id: 'm-invalid-time',
      role: 'assistant',
      content: 'Message with bad timestamp',
      timestamp: 'invalid-date-string'
    };

    expect(() => render(<ChatMessageItem message={message} />)).not.toThrow();
    expect(screen.queryByTestId('message-timestamp')).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // M9 Enhancements: Bottom Toolbar Placement & Class Compliance
  // -------------------------------------------------------------------------
  it('positions action toolbar at the bottom of user message bubble without -top-3.5 or absolute', () => {
    const message: ChatMessage = {
      id: 'm-u-pos',
      role: 'user',
      content: 'Testing bottom toolbar positioning'
    };

    render(<ChatMessageItem message={message} />);
    const toolbar = screen.getByTestId('message-action-toolbar');
    expect(toolbar.className).not.toContain('absolute');
    expect(toolbar.className).not.toContain('-top-');
  });

  it('positions action toolbar at the bottom of assistant message card within footer row', () => {
    const message: ChatMessage = {
      id: 'm-a-pos',
      role: 'assistant',
      content: 'Testing assistant bottom toolbar positioning'
    };

    render(<ChatMessageItem message={message} />);
    const toolbar = screen.getByTestId('message-action-toolbar');
    expect(toolbar.className).not.toContain('absolute');
    expect(toolbar.className).not.toContain('-top-');
  });

  it('uses valid Tailwind v3 shadow-sm class instead of invalid shadow-xs', () => {
    const userMsg: ChatMessage = { id: 'u-shadow', role: 'user', content: 'User shadow' };
    const { container: userContainer } = render(<ChatMessageItem message={userMsg} />);
    expect(userContainer.innerHTML).toContain('shadow-sm');
    expect(userContainer.innerHTML).not.toContain('shadow-xs');

    const assistantMsg: ChatMessage = { id: 'a-shadow', role: 'assistant', content: 'Assistant shadow' };
    const { container: assistantContainer } = render(<ChatMessageItem message={assistantMsg} />);
    expect(assistantContainer.innerHTML).toContain('shadow-sm');
    expect(assistantContainer.innerHTML).not.toContain('shadow-xs');
  });

  // -------------------------------------------------------------------------
  // Markdown Rendering & Asterisks Character Parsing Tests
  // -------------------------------------------------------------------------
  it('renders markdown italics and bold correctly without showing literal asterisk characters', () => {
    const assistantMsg: ChatMessage = {
      id: 'a-md-asterisk',
      role: 'assistant',
      content: 'Here is *italic text* and **bold text** and ***bold italic***.'
    };
    const { container } = render(<ChatMessageItem message={assistantMsg} />);

    // Should contain formatted elements
    const italicEl = container.querySelector('em');
    expect(italicEl).toBeInTheDocument();
    expect(italicEl).toHaveTextContent('italic text');

    const boldEl = container.querySelector('strong');
    expect(boldEl).toBeInTheDocument();
    expect(boldEl).toHaveTextContent('bold text');

    // Content should not show raw markdown asterisk characters
    expect(container.textContent).not.toContain('*italic text*');
    expect(container.textContent).not.toContain('**bold text**');
  });

  it('renders bullet list items starting with asterisk without showing raw asterisk', () => {
    const assistantMsg: ChatMessage = {
      id: 'a-md-list',
      role: 'assistant',
      content: 'Tips for your visit:\n* Bring your insurance card\n* Write down symptoms\n* Arrive 15 minutes early'
    };
    const { container } = render(<ChatMessageItem message={assistantMsg} />);

    const ul = container.querySelector('ul');
    expect(ul).toBeInTheDocument();
    const lis = container.querySelectorAll('li');
    expect(lis).toHaveLength(3);
    expect(lis[0]).toHaveTextContent('Bring your insurance card');
    expect(container.textContent).not.toContain('* Bring');
  });

  it('renders numbered lists correctly', () => {
    const assistantMsg: ChatMessage = {
      id: 'a-md-num-list',
      role: 'assistant',
      content: '1. First step\n2. Second step\n3. Third step'
    };
    const { container } = render(<ChatMessageItem message={assistantMsg} />);

    const ol = container.querySelector('ol');
    expect(ol).toBeInTheDocument();
    const lis = container.querySelectorAll('li');
    expect(lis).toHaveLength(3);
    expect(lis[0]).toHaveTextContent('First step');
  });

  // -------------------------------------------------------------------------
  // Suggestion Leakage Sanitization Tests
  // -------------------------------------------------------------------------
  it('strips leaked internal follow-up questions preamble and raw JSON block from assistant message', () => {
    const leakedContent =
      "These questions will help you understand your deductible and how it applies to your specific situation.assistant\n\n" +
      "Here are 3 concise follow-up questions from the user's perspective:\n\n" +
      "[\n" +
      '  "What are the next steps if I\'ve met my deductible?",\n' +
      '  "Can you explain the Out-of-Pocket Maximum in simpler terms?",\n' +
      '  "How can I confirm my insurance coverage for this procedure?"\n' +
      "]";

    const msg: ChatMessage = {
      id: 'a-leakage',
      role: 'assistant',
      content: leakedContent
    };

    const { container } = render(<ChatMessageItem message={msg} />);
    expect(container.textContent).toContain('These questions will help you understand your deductible and how it applies to your specific situation.');
    expect(container.textContent).not.toContain("Here are 3 concise follow-up questions");
    expect(container.textContent).not.toContain("What are the next steps if I've met my deductible?");
    expect(container.textContent).not.toContain('assistant\n\n');
  });

  // -------------------------------------------------------------------------
  // Reference Document Preamble Sanitization Tests
  // -------------------------------------------------------------------------
  describe('stripReferencePreamble helper', () => {
    it('strips plain "Based on the provided reference document,"', () => {
      const input = 'Based on the provided reference document, here are some questions to ask:';
      expect(stripReferencePreamble(input)).toBe('Here are some questions to ask:');
    });

    it('strips bold "**Based on the provided reference guide:**"', () => {
      const input = '**Based on the provided reference guide:** Here are key items to prepare.';
      expect(stripReferencePreamble(input)).toBe('Here are key items to prepare.');
    });

    it('strips "According to the reference checklist provided:"', () => {
      const input = 'According to the reference checklist provided: bring your photo ID and lab reports.';
      expect(stripReferencePreamble(input)).toBe('Bring your photo ID and lab reports.');
    });

    it('preserves user or standard clinical sentences untouched', () => {
      const input = 'Here are 3 questions to ask your cardiologist about your blood pressure.';
      expect(stripReferencePreamble(input)).toBe(input);
    });
  });

  it('renders assistant message with reference document preamble stripped in chat bubble', () => {
    const msg: ChatMessage = {
      id: 'a-preamble',
      role: 'assistant',
      content: 'Based on the provided reference document, you should review your deductible and copay amounts.'
    };

    const { container } = render(<ChatMessageItem message={msg} />);
    expect(container.textContent).not.toContain('Based on the provided reference document');
    expect(container.textContent).toContain('You should review your deductible and copay amounts.');
  });

  // -------------------------------------------------------------------------
  // Milestone 3 (Issue #86): Dedicated Emergency Escalation Card Tests
  // -------------------------------------------------------------------------
  describe('Emergency Escalation Card (#86)', () => {
    it('renders dedicated EmergencyEscalationCard when message is marked isEmergency', () => {
      const emergencyMsg: ChatMessage = {
        id: 'msg-emerg-1',
        role: 'assistant',
        content: 'EMERGENCY WARNING: Acute crushing chest pain detected. Call 911 immediately.',
        isEmergency: true,
        refusalReason: 'emergency_red_flag:crushing_chest_pain'
      };

      render(<ChatMessageItem message={emergencyMsg} />);

      const card = screen.getByTestId('emergency-escalation-card');
      expect(card).toBeInTheDocument();
      expect(card).toHaveAttribute('role', 'alert');
      expect(card).toHaveAttribute('aria-live', 'assertive');

      // Heading and call to actions
      expect(screen.getByTestId('emergency-card-heading')).toHaveTextContent(/This may be an emergency/i);

      const call911Btn = screen.getByTestId('emergency-call-911-btn');
      expect(call911Btn).toHaveAttribute('href', 'tel:911');
      expect(call911Btn).toHaveTextContent(/Call 911/i);

      const findErBtn = screen.getByTestId('emergency-find-er-btn');
      expect(findErBtn).toHaveAttribute('href', expect.stringContaining('maps'));
      expect(findErBtn).toHaveTextContent(/Find Nearest Emergency Room/i);

      // Verbatim backend message
      const backendMsg = screen.getByTestId('emergency-backend-message');
      expect(backendMsg).toHaveTextContent('EMERGENCY WARNING: Acute crushing chest pain detected. Call 911 immediately.');

      // Non-clinical disclaimer
      expect(screen.getByTestId('emergency-nonclinical-disclaimer')).toBeInTheDocument();

      // Does NOT render standard safe-refusal-badge
      expect(screen.queryByTestId('safe-refusal-badge')).not.toBeInTheDocument();
    });

    it('renders emergency card when refusalReason starts with emergency_red_flag even without explicit isEmergency flag', () => {
      const emergencyMsg: ChatMessage = {
        id: 'msg-emerg-2',
        role: 'assistant',
        content: 'EMERGENCY WARNING: Stroke FAST signs detected.',
        isRefusal: true,
        refusalReason: 'emergency_red_flag:stroke_fast'
      };

      render(<ChatMessageItem message={emergencyMsg} />);

      expect(screen.getByTestId('emergency-escalation-card')).toBeInTheDocument();
      expect(screen.getByTestId('emergency-call-911-btn')).toBeInTheDocument();
      expect(screen.queryByTestId('safe-refusal-badge')).not.toBeInTheDocument();
    });

    it('renders 988 crisis lifeline action button when emergencyCategory is suicide_crisis', () => {
      const crisisMsg: ChatMessage = {
        id: 'msg-emerg-3',
        role: 'assistant',
        content: 'CRISIS SUPPORT: Please connect with the Suicide & Crisis Lifeline immediately.',
        isEmergency: true,
        emergencyCategory: 'suicide_crisis',
        refusalReason: 'emergency_red_flag:suicide_crisis'
      };

      render(<ChatMessageItem message={crisisMsg} />);

      const card = screen.getByTestId('emergency-escalation-card');
      expect(card).toBeInTheDocument();

      const call988Btn = screen.getByTestId('emergency-call-988-btn');
      expect(call988Btn).toBeInTheDocument();
      expect(call988Btn).toHaveAttribute('href', 'tel:988');
      expect(call988Btn).toHaveTextContent(/Call or Text 988/i);
    });

    it('preserves generic refusal badge for non-emergency clinical boundary refusals', () => {
      const nonEmergencyRefusal: ChatMessage = {
        id: 'msg-non-emerg',
        role: 'assistant',
        content: SAFE_REFUSAL_TEMPLATE,
        isRefusal: true,
        refusalReason: 'forbidden_intent:diagnose'
      };

      render(<ChatMessageItem message={nonEmergencyRefusal} />);

      expect(screen.queryByTestId('emergency-escalation-card')).not.toBeInTheDocument();
      expect(screen.getByTestId('safe-refusal-badge')).toBeInTheDocument();
      expect(screen.getByTestId('chat-message-refusal')).toBeInTheDocument();
    });
  });
});


