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
          id: 'm1',
          role: 'user',
          content: "I need to get ready for Rosa's cardiology appointment on Tuesday with Dr. Whitfield."
        },
        {
          id: 'm2',
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
});
