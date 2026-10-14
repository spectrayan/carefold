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

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { AttachmentUploader, type AttachedFile } from '@/components/AttachmentUploader';

describe('AttachmentUploader Component (CF-S04)', () => {
  const attachedFiles: AttachedFile[] = [
    { filename: 'clinic_summary.txt', path: 'attachments/clinic_summary.txt', size_bytes: 2048, format: 'text' }
  ];

  it('renders attached files chips with format badge and remove button', () => {
    render(
      <AttachmentUploader
        attachedFiles={attachedFiles}
        onAttach={vi.fn()}
        onRemove={vi.fn()}
      />
    );

    expect(screen.getByText('clinic_summary.txt')).toBeInTheDocument();
    expect(screen.getByText('TEXT')).toBeInTheDocument();
    expect(screen.getByTestId('remove-attachment-clinic_summary.txt')).toBeInTheDocument();
  });

  it('triggers onRemove callback when remove button is clicked', () => {
    const handleRemove = vi.fn();
    render(
      <AttachmentUploader
        attachedFiles={attachedFiles}
        onAttach={vi.fn()}
        onRemove={handleRemove}
      />
    );

    fireEvent.click(screen.getByTestId('remove-attachment-clinic_summary.txt'));
    expect(handleRemove).toHaveBeenCalledWith('clinic_summary.txt');
  });

  it('shows error banner when invalid executable file is selected', async () => {
    render(
      <AttachmentUploader
        attachedFiles={[]}
        onAttach={vi.fn()}
        onRemove={vi.fn()}
      />
    );

    const input = screen.getByTestId('attachment-file-input');
    const badFile = new File(['binary'], 'installer.exe', { type: 'application/x-msdownload' });

    fireEvent.change(input, { target: { files: [badFile] } });

    expect(await screen.findByTestId('attachment-error-banner')).toHaveTextContent(
      'Unsupported file format ".exe"'
    );
  });
});
