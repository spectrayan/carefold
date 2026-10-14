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

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ChatMarkdown } from '@/components/chat/ChatMarkdown';

describe('ChatMarkdown Component', () => {
  it('renders standard paragraphs, bold, italic, and strikethrough', () => {
    const markdown = 'This is **bold**, *italic*, and ~~strikethrough~~.';
    render(<ChatMarkdown content={markdown} />);

    expect(screen.getByText('bold')).toHaveClass('font-semibold');
    expect(screen.getByText('italic')).toBeInTheDocument();
    expect(screen.getByText('strikethrough')).toHaveClass('line-through');
  });

  it('renders GFM tables with header, rows, and responsive scroll container', () => {
    const tableMarkdown = `
Here is your headache log table:

| Date | Time Began | Duration (Hours) | Peak Pain (0-10) | Location (Left/Right/Both) | Aura Present? (Describe) | Acute Med Taken | Relief at 2 Hours (None/Partial/Complete) | Suspected Trigger (Sleep, Stress, Food, Weather) |
|---|---|---|---|---|---|---|---|---|
| 2026-10-01 | 08:30 AM | 4 | 7 | Left | Visual flashing zigzag | Sumatriptan 50mg | Complete | Lack of sleep |
| 2026-10-02 | 02:15 PM | 2 | 5 | Right | None | Ibuprofen 400mg | Partial | Stress |
`;

    const { container } = render(<ChatMarkdown content={tableMarkdown} />);

    const tableWrapper = container.querySelector('.overflow-x-auto');
    expect(tableWrapper).toBeInTheDocument();
    expect(tableWrapper).toHaveClass('max-w-full');
    expect(tableWrapper).toHaveClass('overscroll-x-contain');

    const table = container.querySelector('table');
    expect(table).toBeInTheDocument();
    expect(table).toHaveClass('min-w-max');
    expect(table).toHaveClass('border-collapse');

    const headers = container.querySelectorAll('th');
    expect(headers.length).toBe(9);
    expect(headers[0].textContent).toBe('Date');
    expect(headers[0]).toHaveClass('border-r');
    expect(headers[3].textContent).toBe('Peak Pain (0-10)');
    expect(headers[8].textContent).toBe('Suspected Trigger (Sleep, Stress, Food, Weather)');

    const rows = container.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);

    const firstRowCells = rows[0].querySelectorAll('td');
    expect(firstRowCells[0].textContent).toBe('2026-10-01');
    expect(firstRowCells[0]).toHaveClass('border-r');
    expect(firstRowCells[1].textContent).toBe('08:30 AM');
    expect(firstRowCells[6].textContent).toBe('Sumatriptan 50mg');
    expect(firstRowCells[7].textContent).toBe('Complete');
  });

  it('renders fenced code blocks with language and copy toolbar', () => {
    const codeMarkdown = `
\`\`\`python
def calculate_fluid_target(weight_kg: float) -> float:
    return weight_kg * 30.0
\`\`\`
`;
    render(<ChatMarkdown content={codeMarkdown} />);

    expect(screen.getByText('python')).toBeInTheDocument();
    expect(screen.getByText('calculate_fluid_target')).toBeInTheDocument();
  });

  it('renders inline code with custom styling', () => {
    const inlineMarkdown = 'Take `Sumatriptan 50mg` at onset of migraine aura.';
    const { container } = render(<ChatMarkdown content={inlineMarkdown} />);

    const codeEl = container.querySelector('code');
    expect(codeEl).toBeInTheDocument();
    expect(codeEl?.textContent).toBe('Sumatriptan 50mg');
    expect(codeEl?.className).toContain('font-mono');
  });

  it('renders blockquotes with styled border', () => {
    const quoteMarkdown = '> Important: Always consult your physician before altering dosages.';
    const { container } = render(<ChatMarkdown content={quoteMarkdown} />);

    const bq = container.querySelector('blockquote');
    expect(bq).toBeInTheDocument();
    expect(bq?.textContent).toContain('Important: Always consult your physician');
  });

  it('renders links with secure target and rel attributes', () => {
    const linkMarkdown = 'Read more at [Carefold Guide](https://carefold.local/guide).';
    render(<ChatMarkdown content={linkMarkdown} />);

    const link = screen.getByRole('link', { name: 'Carefold Guide' });
    expect(link).toHaveAttribute('href', 'https://carefold.local/guide');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders Mermaid diagram blocks inside the Mermaid container', () => {
    const mermaidMarkdown = `
\`\`\`mermaid
graph TD
    A[Symptom Onset] --> B{Crushing Chest Pain?}
    B -->|Yes| C[Call 911 Immediately]
    B -->|No| D[Log in Carefold Visit Prep]
\`\`\`
`;
    render(<ChatMarkdown content={mermaidMarkdown} />);

    expect(screen.getByTestId('mermaid-diagram-container')).toBeInTheDocument();
    expect(screen.getByText('Mermaid Diagram')).toBeInTheDocument();
  });
});
