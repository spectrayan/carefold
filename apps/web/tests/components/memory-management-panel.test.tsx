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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryManagementPanel } from '@/components/memory/MemoryManagementPanel';
import * as memoryLib from '@/lib/memory';
import type { MemoryRecord, MemoryStatus } from '@/types/api';

const mockMemories: MemoryRecord[] = [
  {
    key: 'allergy_penicillin',
    value: 'Severe rash with penicillin',
    tier: 'semantic',
    namespace: 'default',
    salience: 1.0,
    created_at: '2026-10-07T12:00:00Z',
    metadata: {
      agent_id: 'cardiology-guide',
      session_id: 'sess-12345',
    },
  },
  {
    key: 'bp_target',
    value: 'Goal blood pressure < 130/80 mmHg',
    tier: 'episodic',
    namespace: 'default',
    salience: 0.8,
    created_at: '2026-10-06T15:30:00Z',
    metadata: {
      agent_id: 'visit-steward',
    },
  },
  {
    key: 'calc_salt',
    value: 'Draft sodium intake tally',
    tier: 'working',
    namespace: 'default',
    salience: 0.5,
  },
];

const mockStatus: MemoryStatus = {
  backend: 'sqlite',
  healthy: true,
  fallback_active: false,
  spector_url: 'http://localhost:7070',
  cooldown_seconds: 0,
};

describe('MemoryManagementPanel Component', () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();

    vi.spyOn(memoryLib, 'fetchMemories').mockResolvedValue(mockMemories);
    vi.spyOn(memoryLib, 'fetchMemoryStatus').mockResolvedValue(mockStatus);
  });

  afterEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders memory list with tier badges, keys, and values', async () => {
    render(<MemoryManagementPanel />);

    expect(screen.getByText('Loading cognitive memories...')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Severe rash with penicillin')).toBeInTheDocument();
      expect(screen.getByText('Goal blood pressure < 130/80 mmHg')).toBeInTheDocument();
      expect(screen.getByText('Draft sodium intake tally')).toBeInTheDocument();
    });

    expect(screen.getByTestId('memory-status-badge')).toHaveTextContent('SQLite Local FTS5 • Healthy');
    expect(screen.getByTestId('memory-card-allergy_penicillin')).toBeInTheDocument();
    expect(screen.getAllByText('[SEMANTIC]')).toHaveLength(2);
    expect(screen.getAllByText('[EPISODIC]')).toHaveLength(2);
    expect(screen.getAllByText('[WORKING]')).toHaveLength(2);
  });

  it('filters memories by keyword search input', async () => {
    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(screen.getByText('Severe rash with penicillin')).toBeInTheDocument();
    });

    const searchInput = screen.getByTestId('memory-search-input');
    fireEvent.change(searchInput, { target: { value: 'blood pressure' } });

    expect(screen.getByText('Goal blood pressure < 130/80 mmHg')).toBeInTheDocument();
    expect(screen.queryByText('Severe rash with penicillin')).not.toBeInTheDocument();
    expect(screen.queryByText('Draft sodium intake tally')).not.toBeInTheDocument();

    // Clear search button
    const clearBtn = screen.getByTestId('clear-memory-search-btn');
    fireEvent.click(clearBtn);

    expect(screen.getByText('Severe rash with penicillin')).toBeInTheDocument();
  });

  it('filters memories by cognitive tier tabs', async () => {
    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(screen.getByText('Severe rash with penicillin')).toBeInTheDocument();
    });

    // Click Episodic tier tab
    const episodicTab = screen.getByTestId('filter-tier-episodic');
    fireEvent.click(episodicTab);

    expect(screen.getByText('Goal blood pressure < 130/80 mmHg')).toBeInTheDocument();
    expect(screen.queryByText('Severe rash with penicillin')).not.toBeInTheDocument();
    expect(screen.queryByText('Draft sodium intake tally')).not.toBeInTheDocument();

    // Click Semantic tier tab
    const semanticTab = screen.getByTestId('filter-tier-semantic');
    fireEvent.click(semanticTab);

    expect(screen.getByText('Severe rash with penicillin')).toBeInTheDocument();
    expect(screen.queryByText('Goal blood pressure < 130/80 mmHg')).not.toBeInTheDocument();

    // Return to All
    fireEvent.click(screen.getByTestId('filter-tier-all'));
    expect(screen.getByText('Draft sodium intake tally')).toBeInTheDocument();
  });

  it('allows editing fact text and saves updates', async () => {
    const updateSpy = vi.spyOn(memoryLib, 'updateMemory').mockResolvedValue({
      ...mockMemories[0],
      value: 'Severe anaphylactic reaction with penicillin',
    });

    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(screen.getByTestId('edit-memory-btn-allergy_penicillin')).toBeInTheDocument();
    });

    // Click Edit button
    fireEvent.click(screen.getByTestId('edit-memory-btn-allergy_penicillin'));

    // Check modal opens
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Edit Clinical Memory')).toBeInTheDocument();

    const textarea = screen.getByTestId('edit-memory-value-input');
    fireEvent.change(textarea, {
      target: { value: 'Severe anaphylactic reaction with penicillin' },
    });

    // Save changes
    fireEvent.click(screen.getByTestId('save-memory-edit-btn'));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        'allergy_penicillin',
        expect.objectContaining({
          value: 'Severe anaphylactic reaction with penicillin',
        })
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Severe anaphylactic reaction with penicillin')).toBeInTheDocument();
      expect(screen.getByTestId('memory-feedback-banner')).toBeInTheDocument();
    });
  });

  it('shows confirmation modal and deletes single memory record', async () => {
    const deleteSpy = vi.spyOn(memoryLib, 'deleteMemory').mockResolvedValue({
      deleted: true,
      key: 'allergy_penicillin',
      namespace: 'default',
    });

    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(screen.getByTestId('delete-memory-btn-allergy_penicillin')).toBeInTheDocument();
    });

    // Click Forget button
    fireEvent.click(screen.getByTestId('delete-memory-btn-allergy_penicillin'));

    // Check alertdialog opens
    const alertdialog = screen.getByRole('alertdialog');
    expect(alertdialog).toBeInTheDocument();
    expect(screen.getByText('Forget This Memory?')).toBeInTheDocument();

    // Confirm forget
    fireEvent.click(screen.getByTestId('confirm-forget-btn'));

    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledWith('allergy_penicillin', 'default');
      expect(screen.queryByTestId('memory-card-allergy_penicillin')).not.toBeInTheDocument();
      expect(screen.getByTestId('memory-feedback-banner')).toHaveTextContent(
        'Forgot memory "allergy_penicillin".'
      );
    });
  });

  it('shows bulk confirmation modal and clears all memories', async () => {
    const clearSpy = vi.spyOn(memoryLib, 'clearAllMemories').mockResolvedValue({
      deleted: true,
      deleted_count: 3,
      namespace: 'default',
    });

    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(screen.getByTestId('forget-all-memories-btn')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('forget-all-memories-btn'));

    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Forget All Memories?')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('confirm-forget-all-btn'));

    await waitFor(() => {
      expect(clearSpy).toHaveBeenCalledWith('default');
      expect(
        screen.getByText(
          "Carefold hasn't saved any long-term memories yet. Important facts from your specialist consultations will appear here."
        )
      ).toBeInTheDocument();
    });
  });

  it('toggles pause session memory collection switch', async () => {
    render(<MemoryManagementPanel />);

    const toggle = screen.getByTestId('toggle-pause-memory');
    expect(toggle).toHaveAttribute('aria-checked', 'false');

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(sessionStorage.getItem('carefold_memory_paused_session')).toBe('true');
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    expect(sessionStorage.getItem('carefold_memory_paused_session')).toBe('false');
  });

  it('renders local-first privacy notice banner', async () => {
    render(<MemoryManagementPanel />);

    expect(screen.getByText('Local-First Privacy Guarantee')).toBeInTheDocument();
    expect(
      screen.getByText(/All episodic and semantic memories reside strictly within your local database/)
    ).toBeInTheDocument();
  });

  it('displays friendly empty state when no memories exist', async () => {
    vi.spyOn(memoryLib, 'fetchMemories').mockResolvedValue([]);

    render(<MemoryManagementPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(
          "Carefold hasn't saved any long-term memories yet. Important facts from your specialist consultations will appear here."
        )
      ).toBeInTheDocument();
    });

    expect(screen.getByTestId('forget-all-memories-btn')).toBeDisabled();
  });
});
