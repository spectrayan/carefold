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

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { ThinkingIndicator } from '@/components/chat/ThinkingIndicator';
import { ChatMessageItem, type ChatMessage } from '@/components/ChatMessageItem';

describe('ThinkingIndicator Component', () => {
  it('renders default text and 3 pulsing dots with accessibility attributes', () => {
    render(<ThinkingIndicator />);

    const root = screen.getByTestId('thinking-indicator');
    expect(root).toBeInTheDocument();
    expect(root).toHaveAttribute('role', 'status');
    expect(root).toHaveAttribute('aria-live', 'polite');

    const dots = screen.getByTestId('thinking-dots');
    expect(dots).toBeInTheDocument();
    expect(dots.children.length).toBe(3);

    const text = screen.getByTestId('thinking-text');
    expect(text).toHaveTextContent('Planning clinical navigation...');
  });

  it('renders custom text when text prop is provided', () => {
    render(<ThinkingIndicator text="Thinking..." />);
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Thinking...');
  });

  it('applies theme-aware text contrast classes', () => {
    render(<ThinkingIndicator />);
    const root = screen.getByTestId('thinking-indicator');
    expect(root.className).toContain('text-slate-500');
    expect(root.className).toContain('dark:text-zinc-400');
  });
});

describe('ChatMessageItem Thinking & Streaming Transitions', () => {
  it('renders ThinkingIndicator when assistant message is streaming and content is empty', () => {
    const msg: ChatMessage = {
      id: 'msg-empty-stream',
      role: 'assistant',
      content: '',
      isStreaming: true
    };

    render(<ChatMessageItem message={msg} />);
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
  });

  it('renders ThinkingIndicator when content contains only whitespace during streaming', () => {
    const msg: ChatMessage = {
      id: 'msg-whitespace-stream',
      role: 'assistant',
      content: '   \n  \t ',
      isStreaming: true
    };

    render(<ChatMessageItem message={msg} />);
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
  });

  it('switches to streaming cursor when tokens arrive (content.length > 0)', () => {
    const msg: ChatMessage = {
      id: 'msg-active-stream',
      role: 'assistant',
      content: 'Here is what you need to know about your deductible:',
      isStreaming: true
    };

    render(<ChatMessageItem message={msg} />);
    expect(screen.queryByTestId('thinking-indicator')).not.toBeInTheDocument();
    expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument();
  });

  it('renders dynamic tool execution text when active running traces are present', () => {
    const msg: ChatMessage = {
      id: 'msg-tool-stream',
      role: 'assistant',
      content: '',
      isStreaming: true,
      toolTraces: [
        {
          id: 'trace-run',
          tool: 'extract_document_dossier',
          status: 'running'
        }
      ]
    };

    render(<ChatMessageItem message={msg} />);
    expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('thinking-text')).toHaveTextContent('Executing clinical tools...');
  });

  it('renders neither indicator when streaming is finished', () => {
    const msg: ChatMessage = {
      id: 'msg-finished',
      role: 'assistant',
      content: 'Your deductible is $500.',
      isStreaming: false
    };

    render(<ChatMessageItem message={msg} />);
    expect(screen.queryByTestId('thinking-indicator')).not.toBeInTheDocument();
    expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
  });
});
