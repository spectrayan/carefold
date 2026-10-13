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
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { RecordSearch } from '@/components/library/RecordSearch';
import { LibraryClient } from '@/app/library/LibraryClient';

const mockPush = vi.fn();
const mockReplace = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    prefetch: vi.fn()
  }),
  useSearchParams: () => mockSearchParams
}));

describe('RecordSearch Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders initial search state with search input, mode select, and submit button', () => {
    render(<RecordSearch profileId="prof_123" />);

    expect(screen.getByTestId('record-search-container')).toBeInTheDocument();
    expect(screen.getByTestId('record-search-input')).toBeInTheDocument();
    expect(screen.getByTestId('record-search-mode-select')).toBeInTheDocument();
    expect(screen.getByTestId('record-search-submit')).toBeInTheDocument();
    expect(screen.getByText('Cognitive Hybrid Search')).toBeInTheDocument();
  });

  it('performs search and renders matching records with snippets and scores', async () => {
    const mockResults = [
      {
        document_id: 'cardiac_labs.pdf',
        chunk_id: 'cardiac_labs.pdf#c0',
        content: 'Patient eGFR is 42 mL/min indicating Stage 3b chronic kidney disease.',
        score: 0.892,
        profile_id: 'prof_123',
        metadata: {
          filename: 'cardiac_labs.pdf',
          source: 'attachment'
        }
      },
      {
        document_id: 'nephrology-visit.md',
        chunk_id: 'nephrology-visit.md#c1',
        content: 'Recommended dietary adjustments: low sodium, manage blood pressure.',
        score: 0.745,
        profile_id: 'prof_123',
        metadata: {
          title: 'Nephrology Follow-up',
          source: 'note'
        }
      }
    ];

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockResults)
      })
    );

    const onSelectNote = vi.fn();
    render(<RecordSearch profileId="prof_123" onSelectNote={onSelectNote} />);

    const input = screen.getByTestId('record-search-input');
    fireEvent.change(input, { target: { value: 'eGFR 42' } });

    const submitBtn = screen.getByTestId('record-search-submit');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId('record-search-results')).toBeInTheDocument();
    });

    expect(screen.getByText('Found 2 relevant records')).toBeInTheDocument();
    expect(screen.getByText('cardiac_labs.pdf')).toBeInTheDocument();
    expect(screen.getByText(/Patient eGFR is 42/)).toBeInTheDocument();
    expect(screen.getByText('score: 0.892')).toBeInTheDocument();

    expect(screen.getByText('Nephrology Follow-up')).toBeInTheDocument();
    expect(screen.getByText(/low sodium, manage blood pressure/)).toBeInTheDocument();
    expect(screen.getByText('score: 0.745')).toBeInTheDocument();
  });

  it('renders empty results state when query matches nothing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve([])
      })
    );

    render(<RecordSearch profileId="prof_123" />);

    const input = screen.getByTestId('record-search-input');
    fireEvent.change(input, { target: { value: 'nonexistent term' } });

    fireEvent.click(screen.getByTestId('record-search-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('record-search-empty')).toBeInTheDocument();
    });

    expect(screen.getByText('No matching records found')).toBeInTheDocument();
  });

  it('renders error alert when search API returns error response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        json: () => Promise.resolve({ detail: 'Forbidden: profile access denied' })
      })
    );

    render(<RecordSearch profileId="prof_forbidden" />);

    const input = screen.getByTestId('record-search-input');
    fireEvent.change(input, { target: { value: 'test' } });

    fireEvent.click(screen.getByTestId('record-search-submit'));

    await waitFor(() => {
      expect(screen.getByTestId('record-search-error')).toBeInTheDocument();
    });

    expect(screen.getByText('Forbidden: profile access denied')).toBeInTheDocument();
  });

  it('integrates seamlessly into LibraryClient via Search Records tab', () => {
    render(<LibraryClient initialAttachments={[]} initialNotes={[]} />);

    const searchTab = screen.getByTestId('tab-search');
    expect(searchTab).toBeInTheDocument();
    expect(searchTab).toHaveTextContent('Search Records');

    fireEvent.click(searchTab);

    expect(screen.getByTestId('tab-search-content')).toBeInTheDocument();
    expect(screen.getByTestId('record-search-container')).toBeInTheDocument();
  });
});
