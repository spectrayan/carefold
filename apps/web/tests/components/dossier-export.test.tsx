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

import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { DossierExportMenu } from '@/components/chat/DossierExportMenu';
import { ChatClient } from '@/app/chat/ChatClient';
import type { ChatMessage } from '@/lib/types';
import type { AgentSummary } from '@/types/api';

const mockAgents: AgentSummary[] = [
  {
    id: 'visit-steward',
    title: 'Visit Steward',
    version: '0.4.0',
    risk_class: 'clinical_assist',
    skills: ['visit-prep', 'emergency-red-flags'],
    effectiveTools: ['attach-read', 'workspace-note'],
    starters: ['Help me prepare for my doctor visit'],
    description: 'Prepares clinical visit checklists and symptom summaries.',
  },
  {
    id: 'cardiology-guide',
    title: 'Cardiology Guide',
    version: '0.4.0',
    risk_class: 'clinical_assist',
    skills: ['cardiology-prep'],
    effectiveTools: ['attach-read'],
    starters: ['What should I ask my cardiologist?'],
    description: 'Cardiovascular pre-visit guidance.',
  },
];

const mockMessages: ChatMessage[] = [
  {
    id: 'msg-user-1',
    role: 'user',
    content: 'I have had occasional palpitations when exercising.',
    timestamp: '2026-10-07T04:00:00.000Z',
  },
  {
    id: 'msg-assistant-1',
    role: 'assistant',
    content: 'Here is a list of symptom details and questions for your cardiologist.',
    timestamp: '2026-10-07T04:00:30.000Z',
  },
];

describe('DossierExportMenu Component & ChatClient Integration', () => {
  let createdUrls: string[] = [];
  let revokedUrls: string[] = [];
  let clickedAnchors: HTMLAnchorElement[] = [];

  beforeEach(() => {
    localStorage.clear();
    createdUrls = [];
    revokedUrls = [];
    clickedAnchors = [];

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    }));

    vi.spyOn(window.URL, 'createObjectURL').mockImplementation(() => {
      const url = `blob:test-${Math.random().toString(36).substring(2, 9)}`;
      createdUrls.push(url);
      return url;
    });

    vi.spyOn(window.URL, 'revokeObjectURL').mockImplementation((url: string) => {
      revokedUrls.push(url);
    });

    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clickedAnchors.push(this);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  describe('DossierExportMenu Isolated Component', () => {
    it('renders the trigger button with data-testid="export-dossier-menu-btn" and download icon', () => {
      render(
        <DossierExportMenu
          messages={[]}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      expect(btn).toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-haspopup', 'menu');
      expect(btn).toHaveAttribute('aria-expanded', 'false');
      expect(btn.querySelector('svg')).toBeInTheDocument();
    });

    it('is disabled when messages list is empty', () => {
      render(
        <DossierExportMenu
          messages={[]}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      expect(btn).toBeDisabled();
      expect(btn).toHaveAttribute('title', 'No messages to export');
    });

    it('is disabled when isStreaming is true even if messages exist', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={true}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      expect(btn).toBeDisabled();
      expect(btn).toHaveAttribute('title', 'Cannot export while response is generating');
    });

    it('is enabled when messages exist and isStreaming is false', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      expect(btn).not.toBeDisabled();
      expect(btn).toHaveAttribute('title', 'Export consultation dossier');
    });

    it('opens dropdown menu on click with Markdown and JSON options', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();

      fireEvent.click(btn);

      expect(btn).toHaveAttribute('aria-expanded', 'true');
      const menu = screen.getByRole('menu');
      expect(menu).toBeInTheDocument();

      const mdOption = screen.getByTestId('export-markdown-option');
      const jsonOption = screen.getByTestId('export-json-option');

      expect(mdOption).toBeInTheDocument();
      expect(mdOption).toHaveAttribute('role', 'menuitem');
      expect(mdOption.textContent).toContain('Markdown (.md)');

      expect(jsonOption).toBeInTheDocument();
      expect(jsonOption).toHaveAttribute('role', 'menuitem');
      expect(jsonOption.textContent).toContain('JSON (.json)');
    });

    it('clicking Markdown option triggers browser file download and closes menu', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      fireEvent.click(btn);

      const mdOption = screen.getByTestId('export-markdown-option');
      fireEvent.click(mdOption);

      expect(createdUrls).toHaveLength(1);
      expect(clickedAnchors).toHaveLength(1);
      expect(clickedAnchors[0].download).toMatch(/^carefold-visit-steward-prep-\d{4}-\d{2}-\d{2}\.md$/);
      expect(revokedUrls).toHaveLength(1);

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-expanded', 'false');
    });

    it('clicking JSON option triggers browser file download and closes menu', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      fireEvent.click(btn);

      const jsonOption = screen.getByTestId('export-json-option');
      fireEvent.click(jsonOption);

      expect(createdUrls).toHaveLength(1);
      expect(clickedAnchors).toHaveLength(1);
      expect(clickedAnchors[0].download).toMatch(/^carefold-visit-steward-prep-\d{4}-\d{2}-\d{2}\.json$/);
      expect(revokedUrls).toHaveLength(1);

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-expanded', 'false');
    });

    it('closes menu on Escape key press and refocuses trigger button', () => {
      render(
        <DossierExportMenu
          messages={mockMessages}
          agent={mockAgents[0]}
          agentId="visit-steward"
          threadId="thread-1"
          isStreaming={false}
        />
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      fireEvent.click(btn);
      expect(screen.getByRole('menu')).toBeInTheDocument();

      fireEvent.keyDown(document, { key: 'Escape' });

      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
      expect(btn).toHaveAttribute('aria-expanded', 'false');
      expect(document.activeElement).toBe(btn);
    });

    it('closes menu when clicking outside', () => {
      render(
        <div>
          <span data-testid="outside-element">Outside</span>
          <DossierExportMenu
            messages={mockMessages}
            agent={mockAgents[0]}
            agentId="visit-steward"
            threadId="thread-1"
            isStreaming={false}
          />
        </div>
      );

      const btn = screen.getByTestId('export-dossier-menu-btn');
      fireEvent.click(btn);
      expect(screen.getByRole('menu')).toBeInTheDocument();

      fireEvent.mouseDown(screen.getByTestId('outside-element'));
      expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    });
  });

  describe('ChatClient Header Integration', () => {
    it('renders DossierExportMenu between ModelSelector and New Session button in ChatClient header', () => {
      render(<ChatClient initialAgents={mockAgents} />);

      const exportBtn = screen.getByTestId('export-dossier-menu-btn');
      const newSessionBtn = screen.getByTestId('new-session-btn');

      expect(exportBtn).toBeInTheDocument();
      expect(newSessionBtn).toBeInTheDocument();

      // Check header right section hierarchy
      const headerContainer = newSessionBtn.parentElement;
      expect(headerContainer).toContainElement(exportBtn);

      // Verify DOM ordering: ModelSelector -> exportBtn -> newSessionBtn
      const children = Array.from(headerContainer?.children || []);
      const exportIndex = children.indexOf(exportBtn.closest('[data-testid="export-dossier-menu-wrapper"]') || exportBtn);
      const newSessionIndex = children.indexOf(newSessionBtn);
      expect(exportIndex).toBeLessThan(newSessionIndex);
    });

    it('disables export button in ChatClient initially when session is fresh (no messages)', () => {
      render(<ChatClient initialAgents={mockAgents} />);
      const exportBtn = screen.getByTestId('export-dossier-menu-btn');
      expect(exportBtn).toBeDisabled();
    });

    it('enables export button in ChatClient when saved messages are loaded from storage', async () => {
      // Pre-populate thread and messages for default agent
      localStorage.setItem('carefold_thread_visit-steward', 'thread-visit-steward');
      localStorage.setItem('carefold_msgs_thread-visit-steward', JSON.stringify(mockMessages));

      render(<ChatClient initialAgents={mockAgents} />);

      await waitFor(() => {
        const exportBtn = screen.getByTestId('export-dossier-menu-btn');
        expect(exportBtn).not.toBeDisabled();
      });
    });
  });
});
