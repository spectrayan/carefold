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

import path from 'node:path';
import { loadAgent } from '../manifest/agent.js';
import { getClosedTool, executeTool } from '../tools/registry.js';
import { checkSafetyRefusal } from '../safety/classifier.js';
import { SAFE_REFUSAL_TEMPLATE } from '../safety/template.js';
import { recordAudit } from '../audit/logger.js';
import { redactAuditEvent } from '../audit/redaction.js';
import { buildSystemPrompt } from './prompt-builder.js';
import { OpenAIModelClient } from '../model/client.js';
import { MockModelClient } from '../model/mock.js';
import type {
  RunOptions,
  RunResult,
  StreamChunk,
  ToolCallRecord
} from '../types/stream.js';
import type { AuditEvent } from '../types/audit.js';
import type { ExecutionContext } from '../types/context.js';
import type {
  ModelClient,
  ChatMessage,
  ModelToolDefinition,
  ToolCallChunk
} from '../model/types.js';

export async function* executeAgentRun(
  options: RunOptions
): AsyncGenerator<StreamChunk, RunResult, void> {
  const startTime = Date.now();
  const wsRoot = options.workspaceDir || options.workspaceRoot || process.cwd();

  // Resolve agent directory
  let agentDir = options.agentDir;
  if (!agentDir && options.agentId) {
    agentDir = path.resolve(wsRoot, 'agents', options.agentId);
  } else if (agentDir) {
    agentDir = path.resolve(agentDir);
  } else {
    throw new Error('Either agentDir or agentId must be provided in RunOptions.');
  }

  const skillsDir = options.skillsDir
    ? path.resolve(options.skillsDir)
    : path.resolve(wsRoot, 'skills');

  // Load agent and declared skills
  const { agent, effectiveTools, skills } = await loadAgent(agentDir, skillsDir);

  // Setup execution context for tools
  const executionContext: ExecutionContext = {
    workspaceRoot: wsRoot,
    skillsDir,
    agent,
    effectiveTools,
    skills,
    config: options.config
  };

  // Resolve model client
  let client: ModelClient;
  if (options.modelClient) {
    client = options.modelClient;
  } else if (options.mockModel === true) {
    client = new MockModelClient();
  } else if (options.mockModel && typeof (options.mockModel as any).streamChat === 'function') {
    client = options.mockModel as ModelClient;
  } else if (typeof options.mockModel === 'function') {
    const fn = options.mockModel;
    client = {
      getModelName: () => 'custom-mock',
      checkHealth: async () => ({ reachable: true, model: 'custom-mock' }),
      streamChat: (opts) => fn(opts.messages, opts.tools || [])
    };
  } else {
    client = new OpenAIModelClient(options.config?.model);
  }

  // Format tool definitions for model
  const toolDefinitions: ModelToolDefinition[] = [];
  for (const toolName of effectiveTools) {
    const def = getClosedTool(toolName);
    if (def) {
      toolDefinitions.push({
        type: 'function',
        function: {
          name: def.name,
          description: def.description,
          parameters: def.parameters
        }
      });
    }
  }

  const toolCallsRecorded: ToolCallRecord[] = [];
  const auditEventsRecorded: AuditEvent[] = [];

  // Helper ensuring in-memory and on-disk audit events strictly enforce privacy redaction
  const recordAndCollectAudit = async (event: AuditEvent): Promise<AuditEvent> => {
    const safeEvent = redactAuditEvent(event, options.config);
    await recordAudit(safeEvent, options.config, wsRoot);
    auditEventsRecorded.push(safeEvent);
    return safeEvent;
  };

  // Pre-generation Safety Refusal Gate Check (Prompt-Level)
  const promptSafety = checkSafetyRefusal(options.prompt);
  if (promptSafety.refused) {
    const refuseEvent: AuditEvent = {
      ts: new Date().toISOString(),
      agent_id: agent.id,
      event: 'refuse',
      allowed: false,
      reason: promptSafety.reason,
      duration_ms: Date.now() - startTime
    };
    await recordAndCollectAudit(refuseEvent);

    yield {
      type: 'refusal',
      reason: promptSafety.reason || 'Prohibited medical content detected in prompt',
      message: SAFE_REFUSAL_TEMPLATE
    };

    return {
      text: SAFE_REFUSAL_TEMPLATE,
      refused: true,
      refusalReason: promptSafety.reason,
      toolCalls: [],
      auditEvents: auditEventsRecorded
    };
  }

  // Construct initial messages
  const systemPrompt = buildSystemPrompt(agent, skills, effectiveTools);
  const messages: ChatMessage[] = [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: options.prompt }
  ];

  let accumulatedText = '';
  const maxTurns = 5;
  let turn = 0;

  while (turn < maxTurns) {
    turn++;
    const turnToolCallsMap = new Map<number, ToolCallChunk>();
    let turnText = '';

    const stream = client.streamChat({
      messages,
      tools: toolDefinitions.length > 0 ? toolDefinitions : undefined,
      temperature: 0.2
    });

    for await (const chunk of stream) {
      const choice = chunk.choices[0];
      if (!choice) continue;

      const delta = choice.delta;

      // Handle text content streaming
      if (delta.content) {
        turnText += delta.content;
        yield {
          type: 'token',
          delta: delta.content,
          token: delta.content
        };
      }

      // Handle tool call fragments
      if (delta.tool_calls && delta.tool_calls.length > 0) {
        for (const tc of delta.tool_calls) {
          const idx = tc.index ?? 0;
          const existing = turnToolCallsMap.get(idx) || {
            id: tc.id || `call_${idx}`,
            index: idx,
            type: 'function',
            function: { name: '', arguments: '' }
          };

          if (tc.id) existing.id = tc.id;
          if (tc.function?.name) existing.function!.name += tc.function.name;
          if (tc.function?.arguments) existing.function!.arguments += tc.function.arguments;

          turnToolCallsMap.set(idx, existing);
        }
      }
    }

    accumulatedText += turnText;

    // Check if tools were called
    if (turnToolCallsMap.size === 0) {
      // No tools called, agent finished response
      break;
    }

    // Process tool calls
    const pendingCalls = Array.from(turnToolCallsMap.values());
    const assistantMessage: ChatMessage = {
      role: 'assistant',
      content: turnText || null,
      tool_calls: pendingCalls
    };
    messages.push(assistantMessage);

    for (const call of pendingCalls) {
      const toolName = call.function?.name || '';
      let toolArgs: Record<string, any> = {};
      try {
        toolArgs = call.function?.arguments ? JSON.parse(call.function.arguments) : {};
      } catch {
        toolArgs = {};
      }

      const isAllowed = effectiveTools.includes(toolName);
      const callStart = Date.now();

      if (!isAllowed) {
        // Intercept undeclared tool call
        const auditEvent: AuditEvent = {
          ts: new Date().toISOString(),
          agent_id: agent.id,
          event: 'tool',
          tool: toolName,
          allowed: false,
          reason: `Tool "${toolName}" is not declared on agent "${agent.id}" or not in Phase 0 registry.`
        };
        await recordAndCollectAudit(auditEvent);

        const record: ToolCallRecord = {
          tool: toolName,
          input: toolArgs,
          allowed: false,
          duration_ms: 0,
          success: false,
          error: 'Tool execution denied: undeclared tool.'
        };
        toolCallsRecorded.push(record);

        yield {
          type: 'tool_call',
          tool: toolName,
          status: 'denied',
          input: toolArgs,
          result: { success: false, output: null, error: 'Tool execution denied: undeclared tool.' },
          duration_ms: 0
        };

        yield {
          type: 'tool_end',
          tool: toolName,
          result: { success: false, output: null, error: 'Tool execution denied: undeclared tool.' },
          duration_ms: 0,
          allowed: false,
          status: 'denied'
        };

        messages.push({
          role: 'tool',
          tool_call_id: call.id,
          content: `Error: Tool "${toolName}" is not permitted or undeclared for agent "${agent.id}".`
        });
      } else {
        // Execute allowed tool
        yield {
          type: 'tool_start',
          tool: toolName,
          input: toolArgs
        };

        const result = await executeTool(toolName, toolArgs, executionContext);
        const duration = Date.now() - callStart;

        const auditEvent: AuditEvent = {
          ts: new Date().toISOString(),
          agent_id: agent.id,
          event: 'tool',
          tool: toolName,
          allowed: true,
          duration_ms: duration
        };
        await recordAndCollectAudit(auditEvent);

        const record: ToolCallRecord = {
          tool: toolName,
          input: toolArgs,
          allowed: true,
          duration_ms: duration,
          success: result.success,
          output: result.output,
          error: result.error
        };
        toolCallsRecorded.push(record);

        yield {
          type: 'tool_call',
          tool: toolName,
          status: 'allowed',
          input: toolArgs,
          result,
          duration_ms: duration
        };

        yield {
          type: 'tool_end',
          tool: toolName,
          result,
          duration_ms: duration,
          allowed: true,
          status: result.success ? 'completed' : 'failed'
        };

        messages.push({
          role: 'tool',
          tool_call_id: call.id,
          content: JSON.stringify(result.success ? result.output : { error: result.error })
        });
      }
    }
  }

  // Safety Refusal Gate Check
  const safetyResult = checkSafetyRefusal(accumulatedText);
  let finalText = accumulatedText;
  let refused = false;
  let refusalReason: string | undefined;

  if (safetyResult.refused) {
    refused = true;
    refusalReason = safetyResult.reason;
    finalText = SAFE_REFUSAL_TEMPLATE;

    const refuseEvent: AuditEvent = {
      ts: new Date().toISOString(),
      agent_id: agent.id,
      event: 'refuse',
      allowed: false,
      reason: safetyResult.reason,
      duration_ms: Date.now() - startTime
    };
    await recordAndCollectAudit(refuseEvent);

    yield {
      type: 'refusal',
      reason: safetyResult.reason || 'Prohibited medical content detected',
      message: SAFE_REFUSAL_TEMPLATE
    };
  } else {
    // Normal successful run completion
    const runEvent: AuditEvent = {
      ts: new Date().toISOString(),
      agent_id: agent.id,
      event: 'run',
      allowed: true,
      duration_ms: Date.now() - startTime,
      prompt: options.prompt,
      completion: finalText
    };
    await recordAndCollectAudit(runEvent);
  }

  return {
    text: finalText,
    refused,
    refusalReason,
    toolCalls: toolCallsRecorded,
    auditEvents: auditEventsRecorded
  };
}
