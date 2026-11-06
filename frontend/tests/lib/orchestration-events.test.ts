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
import {
  applyOrchestrationEvent,
  applyOrchestrationNotice,
  applyTaskStatus
} from '@/lib/orchestrationEvents';
import type { ChatMessage } from '@/lib/types';

describe('orchestration event reducer', () => {
  it('upserts task_status by task_id so a task shows its latest state once', () => {
    let tasks = applyTaskStatus(undefined, {
      type: 'task_status',
      turn_id: 't1',
      task_id: 'call-1',
      agent_id: 'medication-reviewer',
      state: 'started'
    });
    tasks = applyTaskStatus(tasks, {
      type: 'task_status',
      turn_id: 't1',
      task_id: 'call-2',
      agent_id: 'lab-explainer',
      state: 'started'
    });
    tasks = applyTaskStatus(tasks, {
      type: 'task_status',
      turn_id: 't1',
      task_id: 'call-1',
      agent_id: 'medication-reviewer',
      state: 'timed_out',
      detail: 'Took longer than 60 s'
    });
    expect(tasks).toEqual([
      { taskId: 'call-1', agentId: 'medication-reviewer', state: 'timed_out', detail: 'Took longer than 60 s' },
      { taskId: 'call-2', agentId: 'lab-explainer', state: 'started' }
    ]);
  });

  it('ignores malformed task_status payloads', () => {
    const tasks = applyTaskStatus([], { task_id: '', agent_id: 'x', state: 'started' } as any);
    expect(tasks).toEqual([]);
    expect(applyTaskStatus([], { task_id: 'a', agent_id: 'x', state: 'bogus' } as any)).toEqual([]);
  });

  it('dedupes orchestration notices by code and message', () => {
    const notice = {
      type: 'orchestration_notice' as const,
      turn_id: 't1',
      code: 'partial_failure' as const,
      message: 'One helper could not finish.',
      agent_ids: ['lab-explainer']
    };
    let notices = applyOrchestrationNotice(undefined, notice);
    notices = applyOrchestrationNotice(notices, notice);
    notices = applyOrchestrationNotice(notices, { ...notice, code: 'truncated', message: 'Answer was shortened.', agent_ids: undefined });
    expect(notices).toEqual([
      { code: 'partial_failure', message: 'One helper could not finish.', agentIds: ['lab-explainer'] },
      { code: 'truncated', message: 'Answer was shortened.', agentIds: [] }
    ]);
  });

  it('applies events to a chat message and leaves other events alone', () => {
    const msg: ChatMessage = { id: 'a1', role: 'assistant', content: '' };
    const withTask = applyOrchestrationEvent(msg, 'task_status', {
      task_id: 'call-1',
      agent_id: 'medication-reviewer',
      state: 'completed'
    });
    expect(withTask.taskStatuses).toEqual([
      { taskId: 'call-1', agentId: 'medication-reviewer', state: 'completed' }
    ]);
    const withNotice = applyOrchestrationEvent(withTask, 'orchestration_notice', {
      code: 'model_unavailable',
      message: 'The selected model is unavailable; a fallback answered.'
    });
    expect(withNotice.orchestrationNotices).toHaveLength(1);
    expect(applyOrchestrationEvent(msg, 'token', { delta: 'x' })).toBe(msg);
  });
});
