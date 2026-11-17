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

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { LibraryClient } from '@/app/library/LibraryClient';
import type { AttachmentItem, WorkspaceNoteSummary } from '@/types/api';

const mockPush = vi.fn();
const mockReplace = vi.fn();
let mockSearchParams = new URLSearchParams();

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: mockReplace,
    prefetch: vi.fn(),
  }),
  useSearchParams: () => mockSearchParams,
}));

const mockAttachments: AttachmentItem[] = [
  {
    filename: 'cardiology_discharge_summary.pdf',
    path: 'attachments/cardiology_discharge_summary.pdf',
    size: 24500,
    timestamp: '2026-10-15T14:30:00Z',
  },
  {
    filename: 'blood_glucose_log_october.csv',
    path: 'attachments/blood_glucose_log_october.csv',
    size: 4096,
    timestamp: '2026-10-14T09:15:00Z',
  },
];

const mockNotes: WorkspaceNoteSummary[] = [
  {
    slug: 'cardio-prep-oct15',
    title: 'Cardiology Pre-Visit Preparation',
    agent: 'heart-care-coordinator',
    created_at: '2026-10-15T16:00:00Z',
    size_bytes: 850,
  },
  {
    slug: 'pediatric-sports-form',
    title: 'Pediatric Clearance Notes',
    agent: 'appointment-prep-coordinator',
    created_at: '2026-10-12T11:00:00Z',
    size_bytes: 620,
  },
];

describe('E2E Library & Notes CRUD UI (Feature 5 / Issue #355)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams();
  });

  it('renders library header, tabs, and data residency notice', () => {
    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
      />
    );

    expect(screen.getByRole('heading', { level: 1, name: /Library/i })).toBeInTheDocument();
    expect(screen.getByTestId('data-residency-notice')).toHaveTextContent(
      'Stored on this computer in your Carefold workspace'
    );
    expect(screen.getByTestId('tab-documents')).toBeInTheDocument();
    expect(screen.getByTestId('tab-notes')).toBeInTheDocument();
  });

  it('enforces profile scoping on links and chat deep-links', () => {
    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
        profileId="rosa"
      />
    );

    const useInChat = screen.getByTestId('use-in-chat-cardiology_discharge_summary.pdf');
    expect(useInChat).toBeInTheDocument();
    expect(useInChat).toHaveAttribute('href', '/p/rosa/chat?attach=cardiology_discharge_summary.pdf');
  });

  it('switches to notes tab and renders note cards with title, agent badge, date, and slug', () => {
    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
        profileId="rosa"
      />
    );

    fireEvent.click(screen.getByTestId('tab-notes'));

    expect(screen.getByTestId('notes-grid')).toBeInTheDocument();
    expect(screen.getByTestId('note-title-cardio-prep-oct15')).toHaveTextContent(
      'Cardiology Pre-Visit Preparation'
    );
    expect(screen.getByText('@heart-care-coordinator')).toBeInTheDocument();
    expect(screen.getByText(/cardio-prep-oct15\.md/)).toBeInTheDocument();

    expect(screen.getByTestId('note-title-pediatric-sports-form')).toHaveTextContent(
      'Pediatric Clearance Notes'
    );
    expect(screen.getByText('@appointment-prep-coordinator')).toBeInTheDocument();
  });

  it('opens note detail modal, displays markdown body, and supports copy and export', async () => {
    const mockDetail = {
      slug: 'cardio-prep-oct15',
      title: 'Cardiology Pre-Visit Preparation',
      agent: 'heart-care-coordinator',
      created_at: '2026-10-15T16:00:00Z',
      size_bytes: 850,
      content: '## Pre-Visit Checklist\n\n- [ ] Morning BP readings\n- [ ] List of questions for Dr. Chen',
      raw_content: '---\ntitle: "Cardiology Pre-Visit Preparation"\n---\n\n## Pre-Visit Checklist\n\n- [ ] Morning BP readings\n- [ ] List of questions for Dr. Chen',
      metadata: { title: 'Cardiology Pre-Visit Preparation' },
      path: 'workspace/notes/cardio-prep-oct15.md',
    };

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve(mockDetail),
      })
    );

    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
        profileId="rosa"
      />
    );

    fireEvent.click(screen.getByTestId('tab-notes'));
    const readBtn = screen.getByTestId('read-note-cardio-prep-oct15');
    fireEvent.click(readBtn);

    await waitFor(() => {
      expect(screen.getByTestId('note-detail-modal')).toBeInTheDocument();
    });

    expect(screen.getByTestId('modal-note-title')).toHaveTextContent('Cardiology Pre-Visit Preparation');
    expect(screen.getByText(/Morning BP readings/i)).toBeInTheDocument();
    expect(screen.getByTestId('modal-copy-note')).toBeInTheDocument();
    expect(screen.getByTestId('modal-export-note')).toBeInTheDocument();

    // Close detail modal
    fireEvent.click(screen.getByTestId('modal-close-note'));
    expect(screen.queryByTestId('note-detail-modal')).not.toBeInTheDocument();
  });

  it('filters documents table when search input query is entered', () => {
    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
      />
    );

    const searchInput = screen.getByTestId('library-search-input');
    fireEvent.change(searchInput, { target: { value: 'glucose' } });

    expect(screen.getByText('blood_glucose_log_october.csv')).toBeInTheDocument();
    expect(screen.queryByText('cardiology_discharge_summary.pdf')).not.toBeInTheDocument();
  });

  it('supports direct note creation modal and submission', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'new-note-1',
            slug: 'hypertension-prep',
            title: 'Hypertension Action Plan',
            content: 'Daily morning and evening readings.',
            type: 'visit_prep',
            tags: ['cardio', 'bp'],
          }),
      })
    );

    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
        profileId="rosa"
      />
    );

    fireEvent.click(screen.getByTestId('tab-notes'));
    const createBtn = screen.getByTestId('create-note-button');
    fireEvent.click(createBtn);

    expect(screen.getByTestId('create-note-modal')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('note-title-input'), {
      target: { value: 'Hypertension Action Plan' },
    });
    fireEvent.change(screen.getByTestId('note-content-input'), {
      target: { value: 'Daily morning and evening readings.' },
    });
    fireEvent.change(screen.getByTestId('note-type-select'), {
      target: { value: 'visit_prep' },
    });
    fireEvent.change(screen.getByTestId('note-tags-input'), {
      target: { value: 'cardio, bp' },
    });

    fireEvent.click(screen.getByTestId('save-note-button'));

    await waitFor(() => {
      expect(screen.queryByTestId('create-note-modal')).not.toBeInTheDocument();
    });
  });

  it('supports deleting an attachment from documents list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ deleted: true }),
      })
    );

    render(
      <LibraryClient
        initialAttachments={mockAttachments}
        initialNotes={mockNotes}
        profileId="rosa"
      />
    );

    const deleteBtn = screen.getByTestId('delete-attachment-cardiology_discharge_summary.pdf');
    fireEvent.click(deleteBtn);

    expect(screen.getByTestId('delete-attachment-confirm-modal')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('confirm-delete-attachment-button'));

    await waitFor(() => {
      expect(screen.queryByTestId('delete-attachment-confirm-modal')).not.toBeInTheDocument();
    });
  });
});
