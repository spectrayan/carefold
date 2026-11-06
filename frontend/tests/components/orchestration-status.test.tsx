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
import { render, screen, within } from '@testing-library/react';
import React from 'react';
import { OrchestrationStatus } from '@/components/chat/OrchestrationStatus';

describe('OrchestrationStatus', () => {
  it('renders nothing when there are no tasks or notices', () => {
    const { container } = render(<OrchestrationStatus tasks={[]} notices={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders every task state with an English label', () => {
    render(
      <OrchestrationStatus
        tasks={[
          { taskId: '1', agentId: 'medication-reviewer', state: 'started' },
          { taskId: '2', agentId: 'lab-explainer', state: 'completed' },
          { taskId: '3', agentId: 'insurance-helper', state: 'failed' },
          { taskId: '4', agentId: 'school-forms', state: 'timed_out', detail: 'Took longer than 60 s' },
          { taskId: '5', agentId: 'care-planner', state: 'cancelled' }
        ]}
      />
    );
    const rows = screen.getAllByTestId('task-status-row');
    expect(rows.map((r) => r.getAttribute('data-state'))).toEqual([
      'started',
      'completed',
      'failed',
      'timed_out',
      'cancelled'
    ]);
    const labels = screen.getAllByTestId('task-status-badge').map((b) => b.textContent);
    expect(labels).toEqual(['Working', 'Done', 'Failed', 'Timed out', 'Cancelled']);
    expect(within(rows[0]).getByText('medication-reviewer')).toBeInTheDocument();
    expect(within(rows[3]).getByTestId('task-status-detail')).toHaveTextContent('Took longer than 60 s');
  });

  it('announces a partial_failure notice as a status message', () => {
    render(
      <OrchestrationStatus
        notices={[{ code: 'partial_failure', message: 'One helper could not finish.', agentIds: ['lab-explainer'] }]}
      />
    );
    const notice = screen.getByTestId('orchestration-notice');
    expect(notice).toHaveAttribute('role', 'status');
    expect(notice).toHaveAttribute('data-code', 'partial_failure');
    expect(notice).toHaveTextContent('One helper could not finish.');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
