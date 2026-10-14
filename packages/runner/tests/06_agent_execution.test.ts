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

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import path from 'node:path';
import { executeAgentRun } from '../src/engine/index.js';
import { MockModelClient } from '../src/model/mock.js';
import { OpenAIModelClient } from '../src/model/client.js';
import { parseSSEStream } from '../src/model/sse.js';
import { readAuditEvents } from '../src/audit/logger.js';
import { SAFE_REFUSAL_TEMPLATE } from '../src/safety/template.js';
import { createTestWorkspace, cleanupTestWorkspace } from './helpers/test-workspace.js';

describe('Agent Execution Streaming & Tool Loop', () => {
  let ws: string;
  let mockModel: MockModelClient;

  beforeEach(async () => {
    ws = await createTestWorkspace();
    mockModel = new MockModelClient();
  });

  afterEach(async () => {
    await cleanupTestWorkspace(ws);
  });

  it('streams text completion from mock model client', async () => {
    mockModel.enqueueResponse({ text: 'Hello! I am your care navigation assistant.' });

    const stream = executeAgentRun({
      agentId: 'visit-steward',
      workspaceDir: ws,
      prompt: 'Hello',
      modelClient: mockModel
    });

    const receivedChunks: string[] = [];
    for await (const chunk of stream) {
      if (chunk.type === 'token') {
        receivedChunks.push(chunk.token);
      }
    }

    const fullText = receivedChunks.join('');
    expect(fullText).toContain('Hello! I am your care navigation assistant.');
  });

  it('executes allowed tool call in loop and returns tool result to model', async () => {
    // Turn 1: Model requests workspace-note
    mockModel.enqueueResponse({
      toolCalls: [
        {
          name: 'workspace-note',
          args: { title: 'therapy-q', content: 'Ask about sleep tracking' }
        }
      ]
    });
    // Turn 2: Model finishes with final summary
    mockModel.enqueueResponse({
      text: 'I have saved your questions in your workspace notes.'
    });

    const stream = executeAgentRun({
      agentId: 'visit-steward',
      workspaceDir: ws,
      prompt: 'Help me save questions for my visit',
      modelClient: mockModel
    });

    let toolExecuted = false;
    let finalSummary = '';

    for await (const chunk of stream) {
      if (chunk.type === 'tool_call') {
        expect(chunk.tool).toBe('workspace-note');
        expect(chunk.status).toBe('allowed');
        toolExecuted = true;
      }
      if (chunk.type === 'token') {
        finalSummary += chunk.token;
      }
    }

    expect(toolExecuted).toBe(true);
    expect(finalSummary).toContain('saved your questions');

    // Verify audit log has the tool event
    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const events = await readAuditEvents(auditFile);
    const toolEvent = events.find((e) => e.event === 'tool' && e.tool === 'workspace-note');
    expect(toolEvent).toBeDefined();
    expect(toolEvent?.allowed).toBe(true);
  });

  it('intercepts undeclared tool call, denies execution, and logs audit denial', async () => {
    // Model attempts to call 'attach-read' which visit-steward has NOT declared
    mockModel.enqueueResponse({
      toolCalls: [
        {
          name: 'attach-read',
          args: { path: 'secret.txt' }
        }
      ]
    });
    mockModel.enqueueResponse({ text: 'Understood, tool was not allowed.' });

    const stream = executeAgentRun({
      agentId: 'visit-steward',
      workspaceDir: ws,
      prompt: 'Read secret.txt',
      modelClient: mockModel
    });

    let toolDenied = false;
    for await (const chunk of stream) {
      if (chunk.type === 'tool_call') {
        expect(chunk.tool).toBe('attach-read');
        expect(chunk.status).toBe('denied');
        toolDenied = true;
      }
    }

    expect(toolDenied).toBe(true);

    // Verify audit log recorded tool denial
    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const events = await readAuditEvents(auditFile);
    const deniedEvent = events.find((e) => e.event === 'tool' && e.allowed === false);
    expect(deniedEvent).toBeDefined();
    expect(deniedEvent?.tool).toBe('attach-read');
  });

  it('intercepts diagnostic completion, replaces with safe refusal template, and audits refusal', async () => {
    mockModel.enqueueResponse({
      text: 'Based on your symptoms, you have ADHD.'
    });

    const stream = executeAgentRun({
      agentId: 'visit-steward',
      workspaceDir: ws,
      prompt: 'Do I have ADHD?',
      modelClient: mockModel
    });

    let refusalEmitted = false;
    const result = await (async () => {
      let finalResult;
      for await (const chunk of stream) {
        if (chunk.type === 'refusal') {
          refusalEmitted = true;
          expect(chunk.message).toBe(SAFE_REFUSAL_TEMPLATE);
        }
      }
      return stream;
    })();

    expect(refusalEmitted).toBe(true);

    // Verify audit log recorded refuse event
    const auditFile = path.join(ws, 'logs', 'audit.jsonl');
    const events = await readAuditEvents(auditFile);
    const refuseEvent = events.find((e) => e.event === 'refuse');
    expect(refuseEvent).toBeDefined();
    expect(refuseEvent?.allowed).toBe(false);
    expect(refuseEvent?.reason).toBe('forbidden_intent:diagnose');
  });

  it('correctly handles SSE line-by-line parsing with tool calls and text', async () => {
    const sseLines = [
      'data: {"id":"1","object":"chunk","created":100,"model":"m","choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n',
      'data: {"id":"2","object":"chunk","created":101,"model":"m","choices":[{"index":0,"delta":{"content":" there!"},"finish_reason":"stop"}]}\n\n',
      'data: [DONE]\n\n'
    ].join('');

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sseLines));
        controller.close();
      }
    });

    const parsedChunks: string[] = [];
    for await (const chunk of parseSSEStream(stream, 'test-model')) {
      if (chunk.choices[0]?.delta?.content) {
        parsedChunks.push(chunk.choices[0].delta.content);
      }
    }

    expect(parsedChunks.join('')).toBe('Hi there!');
  });

  it('throws friendly connection error when Ollama server is unreachable', async () => {
    const unreachableClient = new OpenAIModelClient({
      baseUrl: 'http://127.0.0.1:54321/v1',
      timeoutMs: 1000
    });

    const stream = unreachableClient.streamChat({
      messages: [{ role: 'user', content: 'test' }]
    });

    await expect(async () => {
      for await (const _ of stream) {
        // iterate
      }
    }).rejects.toThrow(/Ollama not reachable at http:\/\/127.0.0.1:54321\/v1/i);
  });
});
