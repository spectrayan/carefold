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
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { SessionHistorySidebar } from '@/components/chat/SessionHistorySidebar';
import { CAREFOLD_THREADS_INDEX_KEY, type ChatSessionMeta } from '@/lib/sessionHistory';

describe('SessionHistorySidebar Component', () => {
  const mockSessions: ChatSessionMeta[] = [
    {
      id: 'thread-active-1',
      agentId: 'visit-steward',
      agentTitle: 'Visit Steward',
      title: 'Active Checkup Session',
      createdAt: '2026-10-06T10:00:00.000Z',
      updatedAt: '2026-10-06T11:00:00.000Z',
      messageCount: 4
    },
    {
      id: 'thread-past-2',
      agentId: 'cardiology-guide',
      agentTitle: 'Cardiology Guide',
      title: 'Cardiology Consultation',
      createdAt: '2026-10-05T09:00:00.000Z',
      updatedAt: '2026-10-05T09:30:00.000Z',
      messageCount: 6
    }
  ];

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, JSON.stringify(mockSessions));
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders sidebar with sessions and active indicator when open', () => {
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    const sidebar = screen.getByTestId('session-history-sidebar');
    expect(sidebar).toBeInTheDocument();

    expect(screen.getByText('Active Checkup Session')).toBeInTheDocument();
    expect(screen.getByText('Cardiology Consultation')).toBeInTheDocument();

    // Active session indicator
    const activeItem = screen.getByTestId('session-item-thread-active-1');
    expect(activeItem).toHaveAttribute('aria-current', 'true');

    const pastItem = screen.getByTestId('session-item-thread-past-2');
    expect(pastItem).toHaveAttribute('aria-current', 'false');
  });

  it('calls onSelectSession when a session item is clicked', () => {
    const handleSelect = vi.fn();
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={handleSelect}
        onNewSession={vi.fn()}
      />
    );

    const pastItem = screen.getByTestId('session-item-thread-past-2');
    fireEvent.click(pastItem);

    expect(handleSelect).toHaveBeenCalledWith(mockSessions[1]);
  });

  it('calls onNewSession when New Session button is clicked', () => {
    const handleNewSession = vi.fn();
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={handleNewSession}
      />
    );

    const newSessionBtn = screen.getByTestId('sidebar-new-session-btn');
    fireEvent.click(newSessionBtn);

    expect(handleNewSession).toHaveBeenCalled();
  });

  it('supports inline rename with Enter to save and Escape to cancel', async () => {
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    // Click rename on first session
    const renameBtn = screen.getByTestId('rename-session-thread-active-1');
    fireEvent.click(renameBtn);

    const input = screen.getByTestId('rename-input-thread-active-1') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('Active Checkup Session');

    // Change title and press Enter
    fireEvent.change(input, { target: { value: 'Renamed Checkup Session' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });

    expect(screen.getByText('Renamed Checkup Session')).toBeInTheDocument();

    // Re-enter rename mode and press Escape to cancel
    const renameBtn2 = screen.getByTestId('rename-session-thread-active-1');
    fireEvent.click(renameBtn2);

    const input2 = screen.getByTestId('rename-input-thread-active-1') as HTMLInputElement;
    fireEvent.change(input2, { target: { value: 'Abandoned Title' } });
    fireEvent.keyDown(input2, { key: 'Escape', code: 'Escape' });

    expect(screen.queryByText('Abandoned Title')).not.toBeInTheDocument();
    expect(screen.getByText('Renamed Checkup Session')).toBeInTheDocument();
  });

  it('shows delete confirmation dialog with role alertdialog and deletes session on confirm', () => {
    const handleDelete = vi.fn();
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
        onDeleteSession={handleDelete}
      />
    );

    const deleteBtn = screen.getByTestId('delete-session-thread-past-2');
    fireEvent.click(deleteBtn);

    // Confirmation dialog
    const alertdialog = screen.getByRole('alertdialog');
    expect(alertdialog).toBeInTheDocument();
    expect(alertdialog).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByText(/Delete this conversation\?/i)).toBeInTheDocument();

    // Click confirm delete
    const confirmBtn = screen.getByTestId('confirm-delete-session-btn');
    fireEvent.click(confirmBtn);

    expect(handleDelete).toHaveBeenCalledWith('thread-past-2');
    expect(screen.queryByText('Cardiology Consultation')).not.toBeInTheDocument();
  });

  it('renders friendly empty state when no sessions are stored', () => {
    localStorage.setItem(CAREFOLD_THREADS_INDEX_KEY, JSON.stringify([]));

    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={vi.fn()}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    expect(screen.getByText(/No past conversations yet/i)).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked in mobile drawer view', () => {
    const handleClose = vi.fn();
    render(
      <SessionHistorySidebar
        isOpen={true}
        onClose={handleClose}
        activeThreadId="thread-active-1"
        onSelectSession={vi.fn()}
        onNewSession={vi.fn()}
      />
    );

    const closeBtn = screen.getByTestId('close-history-sidebar-btn');
    fireEvent.click(closeBtn);

    expect(handleClose).toHaveBeenCalled();
  });

  describe('Accessibility Focus Trapping in Delete Dialog', () => {
    it('traps Tab and Shift+Tab keyboard focus between Cancel and Delete buttons', () => {
      render(
        <SessionHistorySidebar
          isOpen={true}
          onClose={vi.fn()}
          activeThreadId="thread-active-1"
          onSelectSession={vi.fn()}
          onNewSession={vi.fn()}
        />
      );

      const deleteBtn = screen.getByTestId('delete-session-thread-past-2');
      fireEvent.click(deleteBtn);

      const cancelBtn = screen.getByTestId('cancel-delete-session-btn');
      const confirmBtn = screen.getByTestId('confirm-delete-session-btn');

      // Initial focus on confirm button
      expect(document.activeElement).toBe(confirmBtn);

      // Press Tab while on confirmBtn -> should wrap to cancelBtn
      fireEvent.keyDown(window, { key: 'Tab', shiftKey: false });
      expect(document.activeElement).toBe(cancelBtn);

      // Press Shift+Tab while on cancelBtn -> should wrap to confirmBtn
      fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
      expect(document.activeElement).toBe(confirmBtn);
    });

    it('returns focus to invoking delete button when dismissed via Cancel button', async () => {
      render(
        <SessionHistorySidebar
          isOpen={true}
          onClose={vi.fn()}
          activeThreadId="thread-active-1"
          onSelectSession={vi.fn()}
          onNewSession={vi.fn()}
        />
      );

      const deleteBtn = screen.getByTestId('delete-session-thread-past-2');
      fireEvent.click(deleteBtn);

      const cancelBtn = screen.getByTestId('cancel-delete-session-btn');
      fireEvent.click(cancelBtn);

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      // Fast-forward timeout for focus restoration
      await vi.waitFor(() => {
        expect(document.activeElement).toBe(deleteBtn);
      });
    });

    it('returns focus to invoking delete button when dismissed via Escape key', async () => {
      render(
        <SessionHistorySidebar
          isOpen={true}
          onClose={vi.fn()}
          activeThreadId="thread-active-1"
          onSelectSession={vi.fn()}
          onNewSession={vi.fn()}
        />
      );

      const deleteBtn = screen.getByTestId('delete-session-thread-past-2');
      fireEvent.click(deleteBtn);

      expect(screen.getByRole('alertdialog')).toBeInTheDocument();

      fireEvent.keyDown(window, { key: 'Escape', code: 'Escape' });

      expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
      await vi.waitFor(() => {
        expect(document.activeElement).toBe(deleteBtn);
      });
    });
  });
});
