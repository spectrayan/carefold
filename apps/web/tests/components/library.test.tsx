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
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { LibraryClient } from '@/app/library/LibraryClient';
import type { AttachmentItem, WorkspaceNoteSummary } from '@/types/api';

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

const sampleAttachments: AttachmentItem[] = [
  {
    filename: 'cardiac_labs.pdf',
    path: 'attachments/cardiac_labs.pdf',
    size: 14500,
    timestamp: '2026-10-07T14:30:00Z'
  },
  {
    filename: 'glucose_readings.csv',
    path: 'attachments/glucose_readings.csv',
    size: 2048,
    timestamp: '2026-10-06T10:15:00Z'
  }
];

const sampleNotes: WorkspaceNoteSummary[] = [
  {
    slug: 'visit-agenda',
    title: 'Cardiovascular Consultation Agenda',
    agent: 'cardiology-guide',
    created_at: '2026-10-07T16:00:00Z',
    size_bytes: 512
  },
  {
    slug: 'sarahs-diabetes-notes',
    title: 'Sarahs Diabetes Management Notes',
    agent: 'visit-steward',
    created_at: '2026-10-05T11:00:00Z',
    size_bytes: 1024
  }
];

describe('LibraryClient Component (Issue #95)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  describe('Header & Data Residency Notice', () => {
    it('renders page title and data residency notice verbatim', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      expect(screen.getByRole('heading', { level: 1, name: /Library/i })).toBeInTheDocument();
      const notice = screen.getByTestId('data-residency-notice');
      expect(notice).toBeInTheDocument();
      expect(notice).toHaveTextContent('Stored on this computer in your Carefold workspace');
    });
  });

  describe('Documents Tab', () => {
    it('renders documents table with filenames, format badges, and Use in chat action', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      expect(screen.getByTestId('documents-table')).toBeInTheDocument();
      expect(screen.getByText('cardiac_labs.pdf')).toBeInTheDocument();
      expect(screen.getByText('glucose_readings.csv')).toBeInTheDocument();
      expect(screen.getByText('PDF')).toBeInTheDocument();
      expect(screen.getByText('CSV')).toBeInTheDocument();

      const useInChatCardiac = screen.getByTestId('use-in-chat-cardiac_labs.pdf');
      expect(useInChatCardiac).toBeInTheDocument();
      expect(useInChatCardiac).toHaveAttribute('href', '/chat?attach=cardiac_labs.pdf');
    });

    it('renders empty state for documents tab when attachments list is empty', () => {
      render(
        <LibraryClient
          initialAttachments={[]}
          initialNotes={sampleNotes}
        />
      );

      const emptyState = screen.getByTestId('documents-empty-state');
      expect(emptyState).toBeInTheDocument();
      expect(screen.getByText('No documents uploaded yet')).toBeInTheDocument();
      expect(
        screen.getByText(/Upload medical records, lab reports, or insurance summaries/i)
      ).toBeInTheDocument();
    });

    it('filters documents list based on search query', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      const searchInput = screen.getByTestId('library-search-input');
      fireEvent.change(searchInput, { target: { value: 'cardiac' } });

      expect(screen.getByText('cardiac_labs.pdf')).toBeInTheDocument();
      expect(screen.queryByText('glucose_readings.csv')).not.toBeInTheDocument();
    });

    it('shows duplicate warning modal when attempting to upload a file with an existing filename', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
      const duplicateFile = new File(['New content'], 'cardiac_labs.pdf', {
        type: 'application/pdf'
      });

      fireEvent.change(fileInput, { target: { files: [duplicateFile] } });

      const modal = screen.getByTestId('duplicate-warning-modal');
      expect(modal).toBeInTheDocument();
      expect(within(modal).getByText('Document already exists')).toBeInTheDocument();
      expect(within(modal).getByText('cardiac_labs.pdf')).toBeInTheDocument();
    });
  });

  describe('Notes Tab', () => {
    it('switches to notes tab and renders note cards with prominent title, agent badge, date, and slug', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      const notesTabButton = screen.getByTestId('tab-notes');
      fireEvent.click(notesTabButton);

      expect(screen.getByTestId('notes-grid')).toBeInTheDocument();
      expect(screen.getByTestId('note-title-visit-agenda')).toHaveTextContent(
        'Cardiovascular Consultation Agenda'
      );
      expect(screen.getByText('@cardiology-guide')).toBeInTheDocument();
      expect(screen.getByText(/visit-agenda\.md/)).toBeInTheDocument();

      expect(screen.getByTestId('note-title-sarahs-diabetes-notes')).toHaveTextContent(
        'Sarahs Diabetes Management Notes'
      );
      expect(screen.getByText('@visit-steward')).toBeInTheDocument();
      expect(screen.getByText(/sarahs-diabetes-notes\.md/)).toBeInTheDocument();
    });

    it('renders empty state for notes tab explaining how files get there', () => {
      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={[]}
        />
      );

      fireEvent.click(screen.getByTestId('tab-notes'));

      const emptyState = screen.getByTestId('notes-empty-state');
      expect(emptyState).toBeInTheDocument();
      expect(screen.getByText('No notes saved yet')).toBeInTheDocument();
      expect(
        screen.getByText(/When Carefold specialist agents/i)
      ).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /Start a consultation/i })).toBeInTheDocument();
    });

    it('opens note detail modal and renders markdown content, title, copy and export buttons', async () => {
      const mockNoteDetail = {
        slug: 'visit-agenda',
        title: 'Cardiovascular Consultation Agenda',
        agent: 'cardiology-guide',
        created_at: '2026-10-07T16:00:00Z',
        size_bytes: 512,
        content: '# Agenda\n\n1. Review blood pressure log\n2. Discuss medication timing',
        raw_content: '---\ntitle: "Cardiovascular Consultation Agenda"\n---\n\n# Agenda\n\n1. Review blood pressure log\n2. Discuss medication timing',
        metadata: { title: 'Cardiovascular Consultation Agenda' },
        path: 'workspace/notes/visit-agenda.md'
      };

      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: true,
          json: () => Promise.resolve(mockNoteDetail)
        })
      );

      render(
        <LibraryClient
          initialAttachments={sampleAttachments}
          initialNotes={sampleNotes}
        />
      );

      fireEvent.click(screen.getByTestId('tab-notes'));
      const readButton = screen.getByTestId('read-note-visit-agenda');
      fireEvent.click(readButton);

      await waitFor(() => {
        expect(screen.getByTestId('note-detail-modal')).toBeInTheDocument();
      });

      expect(screen.getByTestId('modal-note-title')).toHaveTextContent(
        'Cardiovascular Consultation Agenda'
      );
      expect(screen.getByText(/Review blood pressure log/i)).toBeInTheDocument();
      expect(screen.getByTestId('modal-copy-note')).toBeInTheDocument();
      expect(screen.getByTestId('modal-export-note')).toBeInTheDocument();

      // Close modal
      fireEvent.click(screen.getByTestId('modal-close-note'));
      expect(screen.queryByTestId('note-detail-modal')).not.toBeInTheDocument();
    });
  });
});
