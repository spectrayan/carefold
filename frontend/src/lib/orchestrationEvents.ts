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

/**
 * Pure reducers for the orchestration SSE events (`task_status` and
 * `orchestration_notice`). Each assistant message keeps one row per subagent
 * task (latest state wins) and each distinct notice once.
 */

import type {
  ChatMessage,
  OrchestrationNoticeCode,
  OrchestrationNoticeItem,
  TaskState,
  TaskStatusItem
} from '@/lib/types';
import type { SSEOrchestrationNoticeData, SSETaskStatusData } from '@/types/api';

const TASK_STATES: readonly TaskState[] = ['started', 'completed', 'failed', 'timed_out', 'cancelled'];
const NOTICE_CODES: readonly OrchestrationNoticeCode[] = [
  'model_unavailable',
  'main_agent_failed',
  'partial_failure',
  'truncated'
];

export function applyTaskStatus(
  tasks: TaskStatusItem[] | undefined,
  data: SSETaskStatusData
): TaskStatusItem[] {
  const current = tasks || [];
  if (!data || typeof data.task_id !== 'string' || !data.task_id) return current;
  if (!TASK_STATES.includes(data.state)) return current;

  const next: TaskStatusItem = {
    taskId: data.task_id,
    agentId: typeof data.agent_id === 'string' ? data.agent_id : '',
    state: data.state,
    ...(data.detail ? { detail: data.detail } : {})
  };
  const index = current.findIndex((t) => t.taskId === next.taskId);
  if (index === -1) return [...current, next];
  return current.map((t, i) => (i === index ? next : t));
}

export function applyOrchestrationNotice(
  notices: OrchestrationNoticeItem[] | undefined,
  data: SSEOrchestrationNoticeData
): OrchestrationNoticeItem[] {
  const current = notices || [];
  if (!data || !NOTICE_CODES.includes(data.code)) return current;
  if (typeof data.message !== 'string' || !data.message) return current;
  if (current.some((n) => n.code === data.code && n.message === data.message)) return current;
  return [
    ...current,
    {
      code: data.code,
      message: data.message,
      agentIds: Array.isArray(data.agent_ids) ? data.agent_ids : []
    }
  ];
}

/** Apply one SSE event to a message; returns the same object for other events. */
export function applyOrchestrationEvent(message: ChatMessage, eventType: string, data: any): ChatMessage {
  if (eventType === 'task_status') {
    return { ...message, taskStatuses: applyTaskStatus(message.taskStatuses, data) };
  }
  if (eventType === 'orchestration_notice') {
    return { ...message, orchestrationNotices: applyOrchestrationNotice(message.orchestrationNotices, data) };
  }
  return message;
}

export function isOrchestrationEvent(eventType: string): boolean {
  return eventType === 'task_status' || eventType === 'orchestration_notice';
}
