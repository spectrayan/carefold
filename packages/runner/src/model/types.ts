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

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant' | 'tool';
  content: string | null;
  name?: string;
  tool_calls?: ToolCallChunk[];
  tool_call_id?: string;
}

export interface ToolCallChunk {
  id?: string;
  index?: number;
  type?: 'function';
  function?: {
    name?: string;
    arguments?: string;
  };
}

export interface ModelToolDefinition {
  type: 'function';
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface ChatCompletionOptions {
  model?: string;
  messages: ChatMessage[];
  tools?: ModelToolDefinition[];
  temperature?: number;
  maxTokens?: number;
  signal?: AbortSignal;
}

export interface StreamDelta {
  role?: string;
  content?: string | null;
  tool_calls?: ToolCallChunk[];
}

export interface StreamChoice {
  index: number;
  delta: StreamDelta;
  finish_reason: 'stop' | 'tool_calls' | 'length' | null;
}

export interface ModelStreamChunk {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: StreamChoice[];
}

export interface ModelClientConfig {
  provider?: string;         // Default: "ollama"
  baseUrl?: string;          // Default: "http://127.0.0.1:11434/v1"
  model?: string;            // Default: "llama3.2"
  fallbackModels?: string[]; // Default: ["llama3.1:latest", "llama3.1"]
  apiKey?: string;           // Optional
  timeoutMs?: number;        // Default: 30000ms
  mock?: boolean;            // Force offline mock adapter
  temperature?: number;      // Optional
}

export interface ModelClient {
  streamChat(options: ChatCompletionOptions): AsyncGenerator<ModelStreamChunk, void, void>;
  checkHealth(): Promise<{ reachable: boolean; model?: string; error?: string }>;
  getModelName(): string;
}

export class CarefoldModelError extends Error {
  public readonly code: string;
  public readonly isConnectionError: boolean;

  constructor(message: string, code: string, isConnectionError = false) {
    super(message);
    this.name = 'CarefoldModelError';
    this.code = code;
    this.isConnectionError = isConnectionError;
  }
}
