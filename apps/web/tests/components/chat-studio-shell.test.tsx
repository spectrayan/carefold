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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { ChatStudioShell } from '@/components/chat/ChatStudioShell';
import { saveSession } from '@/lib/sessionHistory';
import { saveHouseholdProfiles } from '@/lib/familyProfiles';

describe('ChatStudioShell Component (/p/[profileId]/chat)', () => {
  beforeEach(() => {
    localStorage.clear();
    saveHouseholdProfiles([
      {
        id: 'rosa',
        name: 'Rosa Rivera',
        relationship: 'Mom',
        colorSlot: 3,
        role: 'guardian',
        stats: { chats: 3, items: 12 }
      },
      {
        id: 'leo',
        name: 'Leo Rivera',
        relationship: 'Son',
        colorSlot: 1,
        role: 'viewer',
        stats: { chats: 1, items: 4 }
      }
    ]);
    if (typeof Element.prototype.scrollIntoView !== 'function') {
      Element.prototype.scrollIntoView = vi.fn();
    }
    saveSession({
      id: 'thread-rosa-1',
      agentId: 'visit-steward',
      agentTitle: 'Visit Steward',
      title: 'Cardiology prep for Oct 13',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 2
    });
    localStorage.setItem(
      'carefold_msgs_thread-rosa-1',
      JSON.stringify([
        {
          id: 'msg_one',
          role: 'user',
          content: "I need to get ready for Rosa's cardiology appointment on Tuesday with Dr. Whitfield."
        },
        {
          id: 'msg_two',
          role: 'assistant',
          content: "I'll help you prepare for Rosa's visit on Tuesday, Oct 13. Based on her recent discharge summary, I've put together a starter prep sheet with 4 questions ready to ask her cardiologist."
        }
      ])
    );
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
  });

  it('renders chat studio with thread sidebar, header, and profile context chip', () => {
    render(<ChatStudioShell profileId="rosa" />);

    expect(screen.getByRole('complementary', { name: /rosa rivera's consultation sessions/i })).toBeInTheDocument();
    expect(screen.getByText('Cardiology prep for Oct 13')).toBeInTheDocument();
    expect(screen.getByText('About Rosa')).toBeInTheDocument();
    expect(screen.getAllByText('Visit Steward').length).toBeGreaterThanOrEqual(1);
  });

  it('renders persistent quiet safety footer disclaimer', () => {
    render(<ChatStudioShell profileId="rosa" />);

    expect(screen.getByText(/carefold helps you prepare. it doesn't diagnose. in an emergency, call 911./i)).toBeInTheDocument();
  });

  it('intercepts ambiguous family member prompt with client-side ambiguity hold card', async () => {
    render(<ChatStudioShell profileId="rosa" />);

    const textarea = screen.getByPlaceholderText(/ask visit steward about rosa rivera/i);
    fireEvent.change(textarea, { target: { value: 'Did Leo get his flu vaccine?' } });

    const sendBtn = screen.getByRole('button', { name: /send message/i });
    fireEvent.click(sendBtn);

    // Message must NOT be immediately added to conversation log as sent
    // Instead ambiguity card appears
    await waitFor(() => {
      expect(screen.getByText(/this sounds like it's about leo/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/this chat is about rosa rivera, so i've held that message — it hasn't been sent or saved/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /start a chat for leo/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /keep it in rosa's chat/i })).toBeInTheDocument();
  });

  it('resolves ambiguity by clicking "Keep it in Rosa\'s chat"', async () => {
    render(<ChatStudioShell profileId="rosa" />);

    const textarea = screen.getByPlaceholderText(/ask visit steward about rosa rivera/i);
    fireEvent.change(textarea, { target: { value: 'Did Leo get his flu vaccine?' } });

    const sendBtn = screen.getByRole('button', { name: /send message/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /keep it in rosa's chat/i })).toBeInTheDocument();
    });

    const keepBtn = screen.getByRole('button', { name: /keep it in rosa's chat/i });
    fireEvent.click(keepBtn);

    // Ambiguity card dismissed
    await waitFor(() => {
      expect(screen.queryByText(/this sounds like it's about leo/i)).not.toBeInTheDocument();
    });
  });

  it('sends normal message directly and adds to message stream', async () => {
    render(<ChatStudioShell profileId="rosa" />);

    const textarea = screen.getByPlaceholderText(/ask visit steward about rosa rivera/i);
    fireEvent.change(textarea, { target: { value: 'What questions should I ask Dr. Whitfield about blood pressure?' } });

    const sendBtn = screen.getByRole('button', { name: /send message/i });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getByText('What questions should I ask Dr. Whitfield about blood pressure?')).toBeInTheDocument();
    });
  });

  it('renders starter chips when there are no messages in the active thread', () => {
    // thread-empty has no stored messages
    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-empty" />);

    expect(screen.getByTestId('starters-container')).toBeInTheDocument();
    expect(screen.getByText('Help me prepare for my visit')).toBeInTheDocument();
  });

  it('clicking a starter chip immediately sends the starter prompt', async () => {
    render(<ChatStudioShell profileId="rosa" initialThreadId="thread-empty" />);

    const starterChip = screen.getByText('Help me prepare for my visit');
    fireEvent.click(starterChip);

    await waitFor(() => {
      expect(screen.getByText('Help me prepare for my visit')).toBeInTheDocument();
    });
  });

  it('renders copy button on both user and assistant messages, and regenerate ONLY on assistant messages', () => {
    const { container } = render(<ChatStudioShell profileId="rosa" />);

    // In thread-rosa-1 we have 1 user message and 1 assistant message
    const copyButtons = screen.getAllByTestId('message-copy-btn');
    expect(copyButtons.length).toBe(2);

    // Regenerate button must only exist on assistant messages
    const rerunButtons = screen.getAllByTestId('message-rerun-btn');
    expect(rerunButtons.length).toBe(1);
    expect(rerunButtons[0]).toHaveAttribute('data-action', 'regenerate');

    // Message bubbles must NOT have a border-t footer or author labels
    expect(container.querySelectorAll('.border-t.select-none').length).toBe(0);

    // Message action toolbars must have hover-only styling (opacity-0 group-hover:opacity-100)
    const toolbars = screen.getAllByTestId('message-action-toolbar');
    expect(toolbars.length).toBe(2);
    toolbars.forEach((toolbar) => {
      const parent = toolbar.parentElement;
      expect(parent?.className).toContain('opacity-0');
      expect(parent?.className).toContain('group-hover:opacity-100');
    });
  });

  it('provides an option to delete conversations with confirmation dialog', async () => {
    render(<ChatStudioShell profileId="rosa" />);

    const deleteBtn = screen.getByTestId('delete-thread-thread-rosa-1');
    expect(deleteBtn).toBeInTheDocument();

    fireEvent.click(deleteBtn);

    // Confirmation alertdialog opens
    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Delete conversation?')).toBeInTheDocument();

    const confirmDeleteBtn = screen.getByRole('button', { name: /^delete$/i });
    fireEvent.click(confirmDeleteBtn);

    // Dialog is dismissed and thread is deleted
    await waitFor(() => {
      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      expect(screen.queryByTestId('delete-thread-thread-rosa-1')).not.toBeInTheDocument();
    });
  });
});
